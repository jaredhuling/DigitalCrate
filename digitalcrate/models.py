"""Lazy-loaded ML models: Demucs (stem separation) and CLAP (audio/text embeddings)."""
import warnings
import numpy as np
import torch

from .config import DEMUCS_MODEL, CLAP_MODEL, SR, MODELS_DIR, ROFORMER_MODELS, DATA_DIR

warnings.filterwarnings("ignore")
DEVICE = "mps" if torch.backends.mps.is_available() else "cpu"
import os as _os
if _os.environ.get("DC_THREADS"):  # background jobs (serve.start_job) share the machine with the app
    torch.set_num_threads(int(_os.environ["DC_THREADS"]))

_demucs = None
_clap = None


def separate(y, model=None):
    """y: (2, n) float32 @44.1k -> dict of stems (2, n): drums, bass, other, vocals."""
    global _demucs
    from demucs.pretrained import get_model
    from demucs.apply import apply_model
    name = model or DEMUCS_MODEL
    if _demucs is None or getattr(_demucs, "_dc_name", None) != name:
        _demucs = get_model(name).eval().to(DEVICE)
        _demucs._dc_name = name
    x = torch.from_numpy(y)
    ref = x.mean(0)
    mu, sd = ref.mean(), ref.std() + 1e-8
    x = (x - mu) / sd
    with torch.no_grad():
        try:
            out = _apply_fast(_demucs, x[None])[0]
        except Exception as e:  # anything unexpected (a model of another shape, memory): the library's own way
            print(f"    (fast separation unavailable: {str(e)[:80]})", flush=True)
            out = apply_model(_demucs, x[None], device=DEVICE, shifts=0, split=True,
                              overlap=0.25, progress=False)[0]
    out = (out * sd + mu).cpu().numpy().astype(np.float32)
    return {name: out[i] for i, name in enumerate(_demucs.sources)}


def _apply_fast(bag, mix, overlap=0.25):
    """demucs.apply.apply_model(split=True, shifts=0) for a bag of models, with the segments run a few at a time and,
    on Apple's GPU, in half precision: about a quarter less time for the same stems (they differ from the library's
    by -62 dB, far below hearing; in full precision by nothing). mix: (1, 2, n) -> (1, sources, 2, n)."""
    from demucs.apply import TensorChunk
    from demucs.utils import center_trim
    from .memguard import ram, SMALL_MAC
    B = 2 if 0 < ram() <= SMALL_MAC else 4  # (eight at once on 16 GB swapped and took four times as long)
    half = DEVICE == "mps"
    mix = mix.to(DEVICE)
    length = mix.shape[-1]
    est, totals = 0.0, [0.0] * len(bag.sources)
    for m, w in zip(bag.models, bag.weights):
        seg = int(m.samplerate * m.segment)
        stride = int((1 - overlap) * seg)
        weight = torch.cat([torch.arange(1, seg // 2 + 1, device=DEVICE), torch.arange(seg - seg // 2, 0, -1, device=DEVICE)])
        weight = weight / weight.max()
        out = torch.zeros(1, len(m.sources), mix.shape[1], length, device=DEVICE)
        sw = torch.zeros(length, device=DEVICE)
        offs = list(range(0, length, stride))
        for i in range(0, len(offs), B):
            chunks = [TensorChunk(mix, o, seg) for o in offs[i:i + B]]
            inp = torch.cat([c.padded(seg) for c in chunks], 0)
            if half:
                with torch.autocast("mps", dtype=torch.float16):
                    r = m(inp).float()
            else:
                r = m(inp)
            for c, o, rr in zip(chunks, offs[i:i + B], r):
                rr = center_trim(rr, c.length)
                out[0, ..., o:o + c.length] += weight[:c.length] * rr
                sw[o:o + c.length] += weight[:c.length]
        out /= sw
        for k, iw in enumerate(w):
            out[:, k] *= iw
            totals[k] += iw
        est = est + out
        del out
    for k in range(est.shape[1]):
        est[:, k] /= totals[k]
    if not torch.isfinite(est).all():
        raise ValueError("not finite")
    return est


_rof = {}


def roformer_vocals(path, n_samples, engine="roformer"):
    """High-quality vocal stem via MelBand RoFormer (audio-separator). Returns (2, n) @44.1k."""
    import logging, shutil, soundfile as sf
    from audio_separator.separator import Separator
    tmp = DATA_DIR / "tmp_sep"
    tmp.mkdir(parents=True, exist_ok=True)
    if engine not in _rof:
        sep = Separator(model_file_dir=str(MODELS_DIR), output_dir=str(tmp), output_single_stem="Vocals",
                        output_format="WAV", log_level=logging.WARNING, sample_rate=SR)
        sep.load_model(ROFORMER_MODELS[engine])
        _rof[engine] = sep
    outs = _rof[engine].separate(str(path))
    try:
        v, sr = sf.read(str(tmp / outs[0]), dtype="float32", always_2d=True)
    finally:
        for o in outs:
            (tmp / o).unlink(missing_ok=True)
    v = v.T
    if v.shape[0] == 1:
        v = np.repeat(v, 2, 0)
    if sr != SR:
        from scipy.signal import resample_poly
        v = resample_poly(v, SR, sr, axis=1).astype(np.float32)
    out = np.zeros((2, n_samples), np.float32)
    m = min(n_samples, v.shape[1])
    out[:, :m] = v[:, :m]
    return out


class Clap:
    def __init__(self):
        from transformers import ClapModel, ClapProcessor
        self.model = ClapModel.from_pretrained(CLAP_MODEL).eval().to(DEVICE)
        self.proc = ClapProcessor.from_pretrained(CLAP_MODEL)
        self._text_cache = {}

    @staticmethod
    def _vec(out):
        if isinstance(out, torch.Tensor):
            return out
        return getattr(out, "pooler_output", None) if getattr(out, "pooler_output", None) is not None else out[0]

    def embed_audio(self, clips48):
        """clips48: list of mono float32 arrays at 48 kHz (<=10 s used). Returns (n, d) unit vectors."""
        embs = []
        for i in range(0, len(clips48), 16):
            batch = clips48[i:i + 16]
            inp = self.proc(audio=batch, sampling_rate=48000, return_tensors="pt")
            inp = {k: v.to(DEVICE) for k, v in inp.items()}
            with torch.no_grad():
                e = self._vec(self.model.get_audio_features(**inp))
            embs.append(torch.nn.functional.normalize(e, dim=-1).float().cpu().numpy())
        return np.concatenate(embs) if embs else np.zeros((0, 512), np.float32)

    def embed_text(self, texts):
        key = tuple(texts)
        if key not in self._text_cache:
            inp = self.proc(text=list(texts), return_tensors="pt", padding=True)
            inp = {k: v.to(DEVICE) for k, v in inp.items()}
            with torch.no_grad():
                e = self._vec(self.model.get_text_features(**inp))
            self._text_cache[key] = torch.nn.functional.normalize(e, dim=-1).float().cpu().numpy()
        return self._text_cache[key]


def clap():
    global _clap
    if _clap is None:
        _clap = Clap()
    return _clap
