# Correlation Engine — ROT Feature Reference
> Part of the ROT documentation suite. See [CLAUDE.md](../../CLAUDE.md) for the full index.

## Quick Start for Agents
- Key files: `src/rot/analysis/correlations.py`, `src/rot/analysis/correlation_types.py`, `src/rot/analysis/__init__.py`
- DB tables: None (computed on-demand from `signals`)
- Routes: `GET /correlations`, `GET /api/v1/correlations/matrix`, `GET /api/v1/correlations/{ticker}`, `GET /api/v1/correlations/clusters`, `GET /api/v1/correlations/lead-lag`
- Config: None (uses dashboard query cache TTL of 120s)

---

## Module Layout

| File | Purpose |
|------|---------|
| `__init__.py` | Exports SectorAnalyzer, CorrelationAnalyzer |
| `correlations.py` | Core engine: co-fire correlations, hierarchical clustering, lead-lag detection, network graph |
| `correlation_types.py` | Frozen dataclasses: CorrelationPair, TickerCluster, LeadLagPair, NetworkGraph |

## Data Types

**CorrelationPair**: ticker_a, ticker_b, correlation coefficient, co-fire count, time window

**TickerCluster**: cluster_id, member tickers, centroid ticker, intra-cluster correlation

**LeadLagPair**: leader ticker, follower ticker, lag duration, strength, direction

**NetworkGraph**: nodes (tickers), edges (correlation pairs), clusters -- used for network visualization

## Analysis Components

### Signal Co-Fire Correlations
Measures how frequently two tickers appear in signals within the same time window. Produces a correlation matrix of all ticker pairs with sufficient co-occurrence data. The coefficient reflects the strength of temporal co-occurrence, not price correlation.

### Hierarchical Clustering
Groups tickers into clusters based on their co-fire correlation patterns. Uses a hierarchical approach to identify natural groupings of tickers that tend to be discussed together. Produces `TickerCluster` objects with member lists and intra-cluster correlation metrics.

### Lead-Lag Detection
Identifies directional relationships between ticker signals. When signals for ticker A consistently precede signals for ticker B within a time window, a lead-lag relationship is detected. Reports the leader, follower, typical lag duration, and relationship strength.

### Network Graph Construction
Builds a graph representation suitable for visualization:
- **Nodes**: tickers with signal counts and metadata
- **Edges**: correlation pairs above a minimum threshold
- **Clusters**: color-coded groups from the hierarchical clustering step

The network graph is used by the frontend to render an interactive correlation network.

## Routes

| Method | Path | Description |
|--------|------|-------------|
| GET | `/correlations` | Full dashboard: correlation matrix, clusters, lead-lag, network |
| GET | `/api/v1/correlations/matrix` | JSON API: full correlation matrix |
| GET | `/api/v1/correlations/{ticker}` | JSON API: per-ticker correlations |
| GET | `/api/v1/correlations/clusters` | JSON API: cluster analysis results |
| GET | `/api/v1/correlations/lead-lag` | JSON API: lead-lag relationships |

## On-Demand Analysis Pattern

Like sector rotation, correlation analysis is computed on-demand when the user visits the page. Results are cached via the dashboard query cache with a 120-second TTL. This avoids running expensive matrix computations in a background loop when the data changes relatively slowly.

## Tier Gating

Access is controlled by `gate_correlation_access()` in `src/rot/web/tier_gate.py`. The correlation dashboard and API endpoints are gated by subscription tier.

## Template

The `correlations.html` template displays four sections:
1. **Correlation Matrix** -- heatmap of ticker-pair correlations
2. **Clusters** -- grouped tickers with intra-cluster stats
3. **Lead-Lag Relationships** -- table of leader/follower pairs with lag duration
4. **Network Graph** -- interactive node-edge visualization

## Tests

3 test files:
- `test_correlation_types.py` -- CorrelationPair, TickerCluster, LeadLagPair, NetworkGraph dataclass tests
- `test_correlation_analysis.py` -- Co-fire correlation, clustering, lead-lag detection, network construction
- `test_correlation_db.py` -- Correlation matrix queries, ticker correlations, signal pair queries

## Design Notes

- Correlations are based on signal co-occurrence (social/sentiment signals), not price movements. This is intentional: ROT measures how social discussion patterns correlate across tickers.
- The hierarchical clustering does not require a pre-specified number of clusters; it discovers natural groupings.
- Lead-lag detection requires sufficient signal volume for both tickers to produce statistically meaningful results.
- Memory and computation are bounded by the query cache: once computed, results are served from cache for 120 seconds before recomputation.
- Signal data comes from the unified CTE (live + archived signals) to enable longer-term correlation analysis.
