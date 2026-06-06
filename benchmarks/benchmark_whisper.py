#!/usr/bin/env python3
"""Benchmark faster-whisper transcription latency across model sizes and audio durations.

Generates synthetic test audio (WAV sine wave with modulated frequency to simulate speech),
then runs 10 iterations per (model, duration) configuration and reports mean + p99.
"""

import io
import json
import struct
import time
import wave
from pathlib import Path

import numpy as np
from faster_whisper import WhisperModel

# === Configuration ===
MODEL_SIZES = ["tiny", "base", "small"]
AUDIO_DURATIONS = [5, 30, 60, 120]  # seconds
ITERATIONS = 10
SAMPLE_RATE = 16000
BENCHMARK_DIR = Path(__file__).parent
CACHE_DIR = Path.home() / ".cache" / "whisper_bench"


def generate_synthetic_audio(duration_seconds: int, sample_rate: int = 16000) -> bytes:
    """Generate a WAV file with synthetic 'speech-like' audio: frequency-modulated sine wave."""
    t = np.linspace(0, duration_seconds, int(duration_seconds * sample_rate), endpoint=False)

    # Modulate frequency between 200-800 Hz with varying amplitude to simulate speech
    base_freq = 400.0
    mod_freq = 2.0  # modulation at 2 Hz
    freq = base_freq + 200 * np.sin(2 * np.pi * mod_freq * t)
    phase = 2 * np.pi * np.cumsum(freq) / sample_rate

    # Amplitude modulation to create "syllabic" structure
    amp = 0.5 + 0.5 * np.sin(2 * np.pi * 1.5 * t)
    amp *= 0.3  # scale to avoid clipping

    audio = (amp * np.sin(phase) * 32767).astype(np.int16)

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(audio.tobytes())
    return buf.getvalue()


def benchmark_model(model_size: str, audio_files: dict[int, bytes]) -> list[dict]:
    """Benchmark a single model size across all audio durations."""
    print(f"\n{'='*60}")
    print(f"Loading model: {model_size}")
    print(f"{'='*60}")

    cache_dir = CACHE_DIR / model_size
    cache_dir.mkdir(parents=True, exist_ok=True)

    load_start = time.perf_counter()
    model = WhisperModel(
        model_size,
        device="cpu",
        compute_type="int8",
        download_root=str(CACHE_DIR),
    )
    load_time = time.perf_counter() - load_start
    print(f"Model load time: {load_time:.2f}s")

    results = []
    for duration, audio_bytes in sorted(audio_files.items()):
        print(f"\n  Duration: {duration}s")
        latencies = []

        # Write audio to a temp file (mimics real usage pattern from voice.py)
        temp_path = BENCHMARK_DIR / f"_bench_{duration}s.wav"
        temp_path.write_bytes(audio_bytes)

        for i in range(ITERATIONS):
            start = time.perf_counter()
            segments, info = model.transcribe(str(temp_path), language="de", beam_size=5)
            # Force consumption of all segments
            text = " ".join(seg.text for seg in segments)
            elapsed = time.perf_counter() - start
            latencies.append(elapsed)
            print(f"    Run {i+1:2d}/{ITERATIONS}: {elapsed:.3f}s  (detected: {info.language}, {info.duration:.1f}s)")

        temp_path.unlink(missing_ok=True)

        latencies_np = np.array(latencies)
        results.append({
            "model": model_size,
            "duration_s": duration,
            "iterations": ITERATIONS,
            "mean_s": round(float(np.mean(latencies_np)), 3),
            "median_s": round(float(np.median(latencies_np)), 3),
            "p99_s": round(float(np.percentile(latencies_np, 99)), 3),
            "min_s": round(float(np.min(latencies_np)), 3),
            "max_s": round(float(np.max(latencies_np)), 3),
            "std_s": round(float(np.std(latencies_np)), 3),
            "load_time_s": round(load_time, 2),
        })
        print(f"    Summary: mean={results[-1]['mean_s']}s  p99={results[-1]['p99']}s  min={results[-1]['min_s']}s  max={results[-1]['max_s']}s")

    return results


def print_table(all_results: list[dict]) -> str:
    """Generate a formatted table from results."""
    lines = []
    sep = "-" * 90
    lines.append(sep)
    lines.append(f"{'Model':<8} {'Dur(s)':<7} {'Mean(s)':<10} {'P99(s)':<10} {'Median(s)':<10} {'Min(s)':<10} {'Max(s)':<10} {'Load(s)':<10}")
    lines.append(sep)

    for r in all_results:
        lines.append(
            f"{r['model']:<8} {r['duration_s']:<7} "
            f"{r['mean_s']:<10} {r['p99_s']:<10} {r['median_s']:<10} "
            f"{r['min_s']:<10} {r['max_s']:<10} {r['load_time_s']:<10}"
        )
    lines.append(sep)
    return "\n".join(lines)


def analyze_bottlenecks(all_results: list[dict]) -> str:
    """Identify bottlenecks from results."""
    lines = ["\n## Bottleneck Analysis\n"]

    if not all_results:
        lines.append("  (no results to analyze)")
        return "\n".join(lines)

    # Group by model
    by_model = {}
    for r in all_results:
        by_model.setdefault(r["model"], []).append(r)

    # Load time as overhead
    lines.append("### Model Load Time (cold start overhead)")
    for model, results in by_model.items():
        lines.append(f"  - {model}: {results[0]['load_time_s']:.1f}s to load")

    # Real-time factor (RTF) = processing_time / audio_duration
    lines.append("\n### Real-Time Factor (RTF — lower is better, <1.0 = faster than real-time)")
    for r in all_results:
        rtf = r["mean_s"] / r["duration_s"]
        indicator = "✓" if rtf < 1.0 else "✗"
        lines.append(f"  - {r['model']} @ {r['duration_s']}s: RTF={rtf:.2f} {indicator}")

    # Identify worst case
    lines.append("\n### Slowest Configuration")
    worst = max(all_results, key=lambda r: r["mean_s"])
    lines.append(f"  - Model: {worst['model']}, Duration: {worst['duration_s']}s, Mean: {worst['mean_s']}s")

    # Scalability observation
    lines.append("\n### Scalability")
    for model in MODEL_SIZES:
        model_results = [r for r in all_results if r["model"] == model]
        if len(model_results) >= 2:
            ratio = model_results[-1]["mean_s"] / model_results[0]["mean_s"]
            dur_ratio = model_results[-1]["duration_s"] / model_results[0]["duration_s"]
            lines.append(f"  - {model}: 120s/5s mean ratio = {ratio:.2f}x (linear would be {dur_ratio:.0f}x)")

    return "\n".join(lines)


def main():
    print("=" * 60)
    print("faster-whisper LATENCY BENCHMARK")
    print(f"Device: CPU (Apple Silicon M3)")
    print(f"Iterations per config: {ITERATIONS}")
    print(f"Model sizes: {MODEL_SIZES}")
    print(f"Audio durations: {AUDIO_DURATIONS}s")
    print("=" * 60)

    # Generate audio files
    print("\nGenerating synthetic test audio...")
    audio_files = {}
    for dur in AUDIO_DURATIONS:
        audio_files[dur] = generate_synthetic_audio(dur, SAMPLE_RATE)
        print(f"  {dur}s: {len(audio_files[dur])} bytes")

    # Run benchmarks
    all_results = []
    for model_size in MODEL_SIZES:
        try:
            results = benchmark_model(model_size, audio_files)
            all_results.extend(results)
        except Exception as e:
            print(f"\nERROR benchmarking {model_size}: {e}")
            import traceback
            traceback.print_exc()

    # Print results
    print("\n")
    table = print_table(all_results)
    print(table)

    # Bottleneck analysis
    analysis = analyze_bottlenecks(all_results)
    print(analysis)

    # Save results as JSON
    report = {
        "benchmark": "faster-whisper latency",
        "device": "CPU (Apple Silicon M3)",
        "iterations": ITERATIONS,
        "sample_rate": SAMPLE_RATE,
        "models_tested": MODEL_SIZES,
        "durations_tested_s": AUDIO_DURATIONS,
        "results": all_results,
    }
    report_path = BENCHMARK_DIR / "whisper_bench_results.json"
    report_path.write_text(json.dumps(report, indent=2))
    print(f"\nResults saved to: {report_path}")

    return all_results


if __name__ == "__main__":
    main()
