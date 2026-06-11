"""
ml/infer.py

Inference wrapper to load model weights and classify system telemetry.
"""

from pathlib import Path
import torch

from ml.anomaly_model import AnomalyClassifierMLP

MODEL_PATH = Path(__file__).parent / "anomaly_model.pt"
LABEL_NAMES = ["healthy", "low_output", "offline", "battery_drain", "inverter_fault"]

# Singleton cache for loaded model
_model_cache = None


def get_model() -> AnomalyClassifierMLP:
    """
    Get the loaded PyTorch model. Performs self-training if weights are missing.
    """
    global _model_cache
    if _model_cache is not None:
        return _model_cache

    model = AnomalyClassifierMLP(input_dim=4, num_classes=5)

    if not MODEL_PATH.exists():
        print("Anomaly detection model weights not found. Training model now...")
        from ml.train import train_model
        try:
            train_model()
        except Exception as e:
            print(f"Self-training failed: {e}. Running with uninitialized weights.")

    if MODEL_PATH.exists():
        try:
            model.load_state_dict(torch.load(MODEL_PATH, map_location=torch.device('cpu'), weights_only=True))
        except Exception as e:
            print(f"Failed to load weights: {e}")

    model.eval()
    _model_cache = model
    return model


def predict_anomaly(system_dict: dict) -> str | None:
    """
    Run PyTorch inference to classify system state.

    Returns:
        anomaly_type: One of 'low_output', 'offline', 'battery_drain', 'inverter_fault',
                      or None if classified as healthy.
    """
    # If the system is offline and has no telemetry, classify as offline directly
    # (keeps boundary conditions precise)
    if system_dict.get("solar_output_kw") is None:
        return "offline"

    model = get_model()

    out = system_dict.get("solar_output_kw")
    exp = system_dict.get("expected_output_kw")
    soc = system_dict.get("battery_soc_pct")
    has_battery = 0.0 if system_dict.get("system_type") == "solar_only" else 1.0

    f_out = float(out) if out is not None else 0.0
    f_exp = float(exp) if exp is not None else 0.0
    f_soc = float(soc) if soc is not None else 0.0

    features = torch.tensor([[f_out, f_exp, f_soc, has_battery]], dtype=torch.float32)

    with torch.no_grad():
        outputs = model(features)
        pred_idx = torch.argmax(outputs, dim=1).item()

    predicted_label = LABEL_NAMES[pred_idx]

    if predicted_label == "healthy":
        return None
    return predicted_label
