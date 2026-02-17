# ROT MCP Server — Reddit Options Trader

Real-time trading intelligence from Reddit, RSS, and social media, exposed as MCP tools for any LLM client. Get AI-powered options signals, sentiment analysis, unusual activity alerts, and sports betting intelligence — all through natural language.

## Connect (Zero Install)

Just add the remote URL to your MCP client. No packages to install, no local server to run.

### Claude Desktop

Add this to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "rot": {
      "url": "https://web-production-71423.up.railway.app/mcp"
    }
  }
}
```

### Cursor / Other MCP Clients

Point your MCP client at:

```
https://web-production-71423.up.railway.app/mcp
```

That's it. The server is hosted — no local setup required.

## Available Tools

| Tool | Description | Key Parameters |
|------|-------------|----------------|
| `get_trending_tickers` | Top trending tickers (24h) with signal counts and avg confidence | `hours`, `limit` |
| `get_signals` | Latest trading signals with AI analysis, strategy, and confidence | `ticker`, `stance`, `limit` |
| `get_sentiment` | Bull/bear/mixed ratio and net sentiment score for a ticker | `ticker` (required) |
| `get_market_overview` | 30-day market stats: total signals, win rate, avg confidence | — |
| `get_unusual_activity` | Tickers with IV spikes, volume surges, or OI anomalies | `hours`, `limit` |
| `get_sports_feed` | Sports betting intel with line mover scores (0-100) | `league`, `limit` |
| `search_signals` | Full-text search across all signals | `query` (required), `limit` |

## Resources

| URI | Description |
|-----|-------------|
| `rot://status` | Server health + version |
| `rot://pricing` | Subscription tier info (Free / Pro / Premium / Ultra / Enterprise) |

## Example Prompts

Once connected, try asking your LLM:

- "What stocks are trending on Reddit right now?"
- "Show me bearish signals for TSLA"
- "What's the sentiment on NVDA?"
- "Are there any unusual options activity alerts?"
- "Search for signals about FDA approvals"
- "What NFL news might move betting lines today?"

## Authentication

No API key required — all tools are free at launch. An optional `ROT_API_KEY` env var is supported for future tier gating.

## Links

- **Dashboard**: [web-production-71423.up.railway.app](https://web-production-71423.up.railway.app)
- **GitHub**: [github.com/Mattbusel/Reddit-Options-Trader-ROT-](https://github.com/Mattbusel/Reddit-Options-Trader-ROT-)
