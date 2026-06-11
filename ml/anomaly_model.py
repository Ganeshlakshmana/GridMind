"""
ml/anomaly_model.py

PyTorch model definition for system anomaly classification.
"""

import torch
import torch.nn as nn


class AnomalyClassifierMLP(nn.Module):
    """
    Lightweight Multi-Layer Perceptron (MLP) for classifying system telemetry
    into operational states: [healthy, low_output, offline, battery_drain, inverter_fault].
    """
    def __init__(self, input_dim: int = 4, num_classes: int = 5):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(input_dim, 16),
            nn.ReLU(),
            nn.Linear(16, 8),
            nn.ReLU(),
            nn.Linear(8, num_classes)
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x)
