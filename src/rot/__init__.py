"""rot - Reddit Options Trader signal intelligence platform.

Monitors Reddit and financial news in real time, extracts ticker signals,
enriches them with market data, scores credibility, reasons with LLMs, and
generates structured options trade ideas.

Typical entry point::

    from rot.app.server import main
    main()

The public surface is organised into sub-packages that map one-to-one with
pipeline stages:

- ``rot.ingest``      - Reddit/RSS/StockTwits/Twitter ingestion
- ``rot.trend``       - Trend detection and momentum scoring
- ``rot.nlp``         - 10-module NLP engine (entities, sentiment, temporal)
- ``rot.extract``     - Event builder (dual-path NLP/regex)
- ``rot.market``      - Trade builder, enrichment, symbol validation
- ``rot.credibility`` - ML + heuristic credibility scorer
- ``rot.reasoner``    - LLM reasoning with circuit breaker
- ``rot.alerts``      - Discord, email, Twitter, webhook dispatch
- ``rot.web``         - FastAPI application, routes, auth, middleware
- ``rot.core``        - Config, types, logging, sanitization
"""

__version__ = "0.1.0"
