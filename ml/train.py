"""
ml/train.py

Training script to fit the AnomalyClassifierMLP on synthetic VPP history.
"""

import json
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim

from ml.anomaly_model import AnomalyClassifierMLP

_DATA_DIR = Path(__file__).parent.parent / "data"
FLEET_PATH = _DATA_DIR / "fleet.json"
MODEL_PATH = Path(__file__).parent / "anomaly_model.pt"

LABEL_NAMES = ["healthy", "low_output", "offline", "battery_drain", "inverter_fault"]


def load_dataset() -> tuple[torch.Tensor, torch.Tensor]:
    """
    Load data from fleet.json and extract features and labels for training.
    """
    if not FLEET_PATH.exists():
        raise FileNotFoundError(
            f"fleet.json not found at {FLEET_PATH}. Run data generation first!"
        )

    with open(FLEET_PATH, encoding="utf-8") as f:
        fleet = json.load(f)

    X = []
    y = []

    for system in fleet:
        has_battery = 0.0 if system["system_type"] == "solar_only" else 1.0

        for r in system.get("history", []):
            out = r.get("solar_output_kw")
            exp = r.get("expected_output_kw")
            soc = r.get("battery_soc_pct")
            status = r.get("status")

            # Extract features (default to 0.0 for Nulls/None)
            f_out = float(out) if out is not None else 0.0
            f_exp = float(exp) if exp is not None else 0.0
            f_soc = float(soc) if soc is not None else 0.0

            features = [f_out, f_exp, f_soc, has_battery]

            # Map labels
            if status is None or out is None:
                label = 2  # offline
            elif status == "degraded" and f_out == 0.0:
                label = 4  # inverter_fault
            elif status == "degraded":
                label = 1  # low_output
            elif status == "warning" or (soc is not None and soc < 25.0):
                label = 3  # battery_drain
            else:
                label = 0  # healthy

            X.append(features)
            y.append(label)

    return torch.tensor(X, dtype=torch.float32), torch.tensor(y, dtype=torch.long)


def train_model() -> None:
    """
    Train the MLP model and save its weights.
    """
    X, y = load_dataset()

    print(f"Loaded {len(X)} training samples.")
    model = AnomalyClassifierMLP(input_dim=4, num_classes=5)
    criterion = nn.CrossEntropyLoss()
    optimizer = optim.Adam(model.parameters(), lr=0.01)

    model.train()
    for epoch in range(100):
        optimizer.zero_grad()
        outputs = model(X)
        loss = criterion(outputs, y)
        loss.backward()
        optimizer.step()

        if (epoch + 1) % 20 == 0:
            print(f"Epoch [{epoch+1}/100] - Loss: {loss.item():.4f}")

    # Save weights
    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    torch.save(model.state_dict(), MODEL_PATH)
    print(f"Success - Model trained successfully and weights saved to {MODEL_PATH}")


if __name__ == "__main__":
    train_model()
