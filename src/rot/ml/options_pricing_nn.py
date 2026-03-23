"""
Neural-network-based option pricing (fully numpy-based, no ML libs).

Implements a simple feedforward network trained to replicate Black-Scholes-Merton
prices for European call options, using only Python standard library and math.
"""

import json
import math
import random


def _norm_cdf(x: float) -> float:
    """Approximation of the standard normal CDF using a rational approximation."""
    # Abramowitz and Stegun approximation
    if x < 0:
        return 1.0 - _norm_cdf(-x)
    t = 1.0 / (1.0 + 0.2316419 * x)
    poly = t * (0.319381530
                + t * (-0.356563782
                       + t * (1.781477937
                              + t * (-1.821255978
                                     + t * 1.330274429))))
    return 1.0 - (1.0 / math.sqrt(2 * math.pi)) * math.exp(-0.5 * x * x) * poly


def _bsm_call(S: float, K: float, T: float, r: float, sigma: float) -> float:
    """Black-Scholes-Merton call price."""
    if T <= 0 or sigma <= 0:
        return max(S - K, 0.0)
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return S * _norm_cdf(d1) - K * math.exp(-r * T) * _norm_cdf(d2)


class NeuralOptionPricer:
    """
    A small feedforward neural network that learns to price European call options.

    Architecture: input(5) -> hidden1 -> hidden2 -> output(1)
    Inputs: [S, K, T, r, sigma]
    Output: predicted call price
    """

    def __init__(self, hidden_sizes=None, learning_rate=0.001, seed=42):
        if hidden_sizes is None:
            hidden_sizes = [64, 32]
        self.hidden_sizes = hidden_sizes
        self.learning_rate = learning_rate
        self.seed = seed
        self._rng = random.Random(seed)
        self.weights = []
        self.biases = []
        self._init_weights()

    def _init_weights(self):
        """Xavier initialization."""
        layer_sizes = [5] + self.hidden_sizes + [1]
        self.weights = []
        self.biases = []
        for i in range(len(layer_sizes) - 1):
            fan_in = layer_sizes[i]
            fan_out = layer_sizes[i + 1]
            limit = math.sqrt(6.0 / (fan_in + fan_out))
            W = [
                [self._rng.uniform(-limit, limit) for _ in range(fan_out)]
                for _ in range(fan_in)
            ]
            b = [0.0] * fan_out
            self.weights.append(W)
            self.biases.append(b)

    def relu(self, x):
        """Element-wise ReLU."""
        if isinstance(x, list):
            return [max(0.0, v) for v in x]
        return max(0.0, x)

    def relu_grad(self, x):
        """Element-wise ReLU gradient."""
        if isinstance(x, list):
            return [1.0 if v > 0 else 0.0 for v in x]
        return 1.0 if x > 0 else 0.0

    def _matmul_vec(self, W, x):
        """Matrix-vector multiply: W^T * x where W is [in_dim][out_dim]."""
        out_dim = len(W[0])
        result = [0.0] * out_dim
        for j in range(out_dim):
            for i, xi in enumerate(x):
                result[j] += W[i][j] * xi
        return result

    def _add_vec(self, a, b):
        return [ai + bi for ai, bi in zip(a, b)]

    def _forward_full(self, x: list):
        """Full forward pass returning all layer activations (pre and post)."""
        activations = [x]
        pre_activations = []
        current = x
        for layer_idx, (W, b) in enumerate(zip(self.weights, self.biases)):
            z = self._add_vec(self._matmul_vec(W, current), b)
            pre_activations.append(z)
            if layer_idx < len(self.weights) - 1:
                current = self.relu(z)
            else:
                # Output layer: linear
                current = z
            activations.append(current)
        return activations, pre_activations

    def forward(self, x: list) -> float:
        """Forward pass for a single sample, returns predicted price."""
        activations, _ = self._forward_full(x)
        return activations[-1][0]

    def forward_batch(self, X: list) -> list:
        """Forward pass for a batch."""
        return [self.forward(x) for x in X]

    def backward(self, x: list, y: float, y_hat: float):
        """Single-sample gradient descent update."""
        activations, pre_activations = self._forward_full(x)
        n_layers = len(self.weights)

        # Output error
        delta = [2.0 * (y_hat - y)]  # MSE gradient at output

        for layer_idx in range(n_layers - 1, -1, -1):
            # Gradient w.r.t. weights
            a_in = activations[layer_idx]
            for i in range(len(self.weights[layer_idx])):
                for j in range(len(self.weights[layer_idx][i])):
                    grad = a_in[i] * delta[j]
                    self.weights[layer_idx][i][j] -= self.learning_rate * grad

            # Gradient w.r.t. biases
            for j in range(len(self.biases[layer_idx])):
                self.biases[layer_idx][j] -= self.learning_rate * delta[j]

            # Backpropagate delta if not input layer
            if layer_idx > 0:
                prev_z = pre_activations[layer_idx - 1]
                relu_d = self.relu_grad(prev_z)
                W = self.weights[layer_idx]
                in_dim = len(W)
                new_delta = [0.0] * in_dim
                for i in range(in_dim):
                    for j in range(len(delta)):
                        new_delta[i] += W[i][j] * delta[j]
                    new_delta[i] *= relu_d[i]
                delta = new_delta

    def train(self, X: list, y: list, epochs: int = 100):
        """Train on (S,K,T,r,sigma) -> BSM price pairs."""
        for _ in range(epochs):
            for xi, yi in zip(X, y):
                y_hat = self.forward(xi)
                self.backward(xi, yi, y_hat)

    def predict(self, S: float, K: float, T: float, r: float, sigma: float) -> float:
        """Predict option price for given parameters."""
        return self.forward([S, K, T, r, sigma])

    def mse_loss(self, y_true: list, y_pred: list) -> float:
        """Mean squared error."""
        if not y_true:
            return 0.0
        return sum((yt - yp) ** 2 for yt, yp in zip(y_true, y_pred)) / len(y_true)

    def generate_training_data(self, n: int = 1000):
        """Generate random option inputs with BSM prices as labels."""
        X = []
        y = []
        rng = random.Random(self.seed + 1)
        for _ in range(n):
            S = rng.uniform(50, 200)
            K = rng.uniform(50, 200)
            T = rng.uniform(0.1, 2.0)
            r = rng.uniform(0.01, 0.1)
            sigma = rng.uniform(0.1, 0.8)
            price = _bsm_call(S, K, T, r, sigma)
            X.append([S, K, T, r, sigma])
            y.append(price)
        return X, y

    def save_weights(self, path: str):
        """Save weights and biases to JSON."""
        data = {
            "weights": self.weights,
            "biases": self.biases,
            "hidden_sizes": self.hidden_sizes,
            "learning_rate": self.learning_rate,
            "seed": self.seed,
        }
        with open(path, "w") as f:
            json.dump(data, f)

    def load_weights(self, path: str):
        """Load weights and biases from JSON."""
        with open(path, "r") as f:
            data = json.load(f)
        self.weights = data["weights"]
        self.biases = data["biases"]
        self.hidden_sizes = data["hidden_sizes"]
        self.learning_rate = data["learning_rate"]
        self.seed = data["seed"]
