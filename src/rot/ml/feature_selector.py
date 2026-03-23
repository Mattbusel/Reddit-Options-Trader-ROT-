"""Feature importance and selection using pure Python/numpy.

Provides correlation-based filtering, variance filtering, and mutual
information ranking for feature selection without sklearn.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Optional

import numpy as np


@dataclass
class FeatureImportance:
    """Importance metadata for a single feature."""
    feature_name: str
    importance_score: float
    rank: int
    cumulative_importance: float


class FeatureSelector:
    """Feature selection using correlation, variance, and mutual information.

    All methods use only numpy — no sklearn dependency.

    Example::

        X = np.random.randn(100, 5)
        y = np.random.randn(100)
        names = [f"f{i}" for i in range(5)]
        selector = FeatureSelector()
        importances = selector.mutual_information_importance(X, y, names)
        top = selector.select_top_k(importances, k=3)
    """

    def correlation_filter(
        self,
        X: np.ndarray,
        feature_names: List[str],
        threshold: float = 0.95,
    ) -> List[str]:
        """Remove highly correlated features.

        For each pair with |correlation| > threshold, drop the feature that
        appears later in the list (keep the first).

        Args:
            X: Feature matrix of shape (n_samples, n_features).
            feature_names: Names for each column.
            threshold: Absolute correlation threshold above which to drop.

        Returns:
            List of feature names to keep.
        """
        n_features = X.shape[1]
        if n_features == 0:
            return []

        # Compute Pearson correlation matrix
        corr = np.corrcoef(X, rowvar=False)
        if corr.ndim == 0:
            corr = np.array([[corr]])

        to_drop = set()
        for i in range(n_features):
            if i in to_drop:
                continue
            for j in range(i + 1, n_features):
                if j in to_drop:
                    continue
                if abs(corr[i, j]) > threshold:
                    to_drop.add(j)

        return [name for idx, name in enumerate(feature_names) if idx not in to_drop]

    def variance_filter(
        self,
        X: np.ndarray,
        feature_names: List[str],
        min_variance: float = 0.01,
    ) -> List[str]:
        """Remove near-constant features (variance below threshold).

        Args:
            X: Feature matrix of shape (n_samples, n_features).
            feature_names: Names for each column.
            min_variance: Minimum variance to keep a feature.

        Returns:
            List of feature names with variance >= min_variance.
        """
        variances = np.var(X, axis=0)
        return [
            name
            for name, var in zip(feature_names, variances)
            if var >= min_variance
        ]

    def mutual_information_importance(
        self,
        X: np.ndarray,
        y: np.ndarray,
        feature_names: List[str],
        n_bins: int = 10,
    ) -> List[FeatureImportance]:
        """Rank features by mutual information with the target.

        Discretizes both features and target into equal-width bins, then
        estimates MI(feature_i, target) from the joint frequency table.

        Args:
            X: Feature matrix of shape (n_samples, n_features).
            y: Target array of shape (n_samples,).
            feature_names: Names for each column.
            n_bins: Number of histogram bins for discretization.

        Returns:
            List of FeatureImportance sorted by importance_score descending,
            with rank and cumulative_importance filled in.
        """
        n_samples, n_features = X.shape
        if n_samples == 0 or n_features == 0:
            return []

        y_disc = self._discretize_1d(y, n_bins)

        mi_scores: List[tuple] = []
        for feat_idx in range(n_features):
            col = X[:, feat_idx]
            col_disc = self._discretize_1d(col, n_bins)
            mi = self._mutual_information(col_disc, y_disc, n_bins)
            mi_scores.append((feature_names[feat_idx], mi))

        # Sort descending
        mi_scores.sort(key=lambda x: x[1], reverse=True)

        total_importance = sum(mi for _, mi in mi_scores)
        importances: List[FeatureImportance] = []
        cumulative = 0.0
        for rank, (name, score) in enumerate(mi_scores, start=1):
            if total_importance > 0:
                cumulative += score / total_importance
            else:
                cumulative = rank / len(mi_scores)
            importances.append(
                FeatureImportance(
                    feature_name=name,
                    importance_score=score,
                    rank=rank,
                    cumulative_importance=min(cumulative, 1.0),
                )
            )

        return importances

    def select_top_k(
        self,
        importances: List[FeatureImportance],
        k: int,
    ) -> List[str]:
        """Return feature names for the top-k most important features.

        Assumes `importances` is already sorted by rank ascending.

        Args:
            importances: Sorted list of FeatureImportance (rank 1 = best).
            k: Number of features to select.

        Returns:
            Feature names for the top k features.
        """
        sorted_imp = sorted(importances, key=lambda fi: fi.rank)
        return [fi.feature_name for fi in sorted_imp[:k]]

    def select_cumulative(
        self,
        importances: List[FeatureImportance],
        threshold: float = 0.9,
    ) -> List[str]:
        """Return features that together cover `threshold` fraction of total importance.

        Args:
            importances: Sorted list of FeatureImportance.
            threshold: Fraction of cumulative importance to cover (0-1).

        Returns:
            Minimal set of feature names covering the threshold.
        """
        sorted_imp = sorted(importances, key=lambda fi: fi.rank)
        result = []
        for fi in sorted_imp:
            result.append(fi.feature_name)
            if fi.cumulative_importance >= threshold:
                break
        return result

    # ── Private helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _discretize_1d(values: np.ndarray, bins: int) -> np.ndarray:
        """Discretize a 1-D array into equal-width integer bins."""
        min_val = float(np.min(values))
        max_val = float(np.max(values))
        if max_val == min_val:
            return np.zeros(len(values), dtype=int)
        bin_width = (max_val - min_val) / bins
        disc = ((values - min_val) / bin_width).astype(int)
        np.clip(disc, 0, bins - 1, out=disc)
        return disc

    @staticmethod
    def _mutual_information(
        x_disc: np.ndarray, y_disc: np.ndarray, bins: int
    ) -> float:
        """Estimate MI(X, Y) from discretized arrays using joint frequency table."""
        n = len(x_disc)
        if n == 0:
            return 0.0

        # Joint counts
        joint: dict = {}
        for xi, yi in zip(x_disc, y_disc):
            key = (int(xi), int(yi))
            joint[key] = joint.get(key, 0) + 1

        # Marginal counts
        x_counts: dict = {}
        y_counts: dict = {}
        for (xi, yi), count in joint.items():
            x_counts[xi] = x_counts.get(xi, 0) + count
            y_counts[yi] = y_counts.get(yi, 0) + count

        mi = 0.0
        for (xi, yi), count_xy in joint.items():
            p_xy = count_xy / n
            p_x = x_counts[xi] / n
            p_y = y_counts[yi] / n
            if p_xy > 0.0 and p_x > 0.0 and p_y > 0.0:
                mi += p_xy * math.log(p_xy / (p_x * p_y))

        return max(mi, 0.0)
