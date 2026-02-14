<!-- Optimized for token efficiency. Read by agents on-demand. -->
# Correlation Engine

- **Files**: `src/rot/analysis/{correlations,correlation_types,__init__}.py`
- **DB**: None (computed on-demand from `signals`)
- **Routes**: `GET /correlations`, `GET /api/v1/correlations/{matrix,{ticker},clusters,lead-lag}`
- **Config**: None (uses query cache TTL 120s)
- **Tier**: `gate_correlation_access()`

## Types
- **CorrelationPair**: ticker_a, ticker_b, correlation, co_fire_count, window
- **TickerCluster**: cluster_id, tickers, centroid, intra-cluster correlation
- **LeadLagPair**: leader, follower, lag duration, strength, direction
- **NetworkGraph**: nodes (tickers), edges (correlations), clusters

## Analysis Components
1. **Co-Fire Correlations**: Temporal co-occurrence of tickers in signals (social correlation, not price)
2. **Hierarchical Clustering**: Auto-discovers ticker groupings from co-fire patterns
3. **Lead-Lag Detection**: Identifies when ticker A signals consistently precede ticker B
4. **Network Graph**: Nodes + edges + clusters for frontend visualization

## On-Demand Pattern
Computed when user visits page, cached 120s via query cache. Uses unified CTE (live + archived signals).

## Template (`correlations.html`)
4 sections: correlation matrix heatmap, clusters, lead-lag table, interactive network graph

## Tests
`test_correlation_{types,analysis,db}.py`
