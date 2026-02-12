# ROT Backburner — Future Features

Items deferred from the current sprint. These are good ideas that need more design
or dedicated time before implementation.

---

## 1. Mobile Responsive Layout

**Priority:** Medium
**Effort:** Medium (2-3 days)

The current dashboard uses Tailwind's responsive classes but hasn't been
systematically tested on mobile viewports. Key work:

- Audit every page at 375px, 414px, and 768px breakpoints
- Collapse nav into hamburger menu on small screens
- Stack chart/table layouts vertically on mobile
- Ensure touch targets are >= 44px
- Test WebSocket reconnect on mobile (network transitions)
- Consider a PWA manifest for "Add to Home Screen"

**Files to touch:** `base.html`, `dashboard.html`, every template.

---

## 2. Social Share Cards (OG Image Generation)

**Priority:** Medium
**Effort:** Medium (1-2 days)

Auto-generate Open Graph images for signal detail pages so that shared links
on Twitter/Reddit/Discord show a rich preview card with:

- Ticker, stance, confidence bar
- Price movement chart (mini sparkline)
- Win/loss badge
- ROT branding

**Approach options:**
- **Server-side:** Use Pillow/PIL to render a PNG on demand, cache in `/static/og/`
- **Edge function:** Use a Vercel/Cloudflare Worker with Satori (HTML-to-SVG)
- **Prerender:** Generate during the cleanup cycle for recent signals

**Files to touch:** `signal_detail.html` (meta tags), new `og_generator.py`, static route.

---

## 3. ML Scorer (Replace Heuristic Credibility)

**Priority:** Low (high impact, high effort)
**Effort:** High (1-2 weeks)

Replace the rule-based `CredibilityScorer` with a trained model that learns
from historical win/loss outcomes. Steps:

1. **Feature engineering:** Extract ~30 features from each signal (subreddit,
   flair, body length, entity count, score, upvote ratio, author karma,
   author age, time of day, day of week, ATM IV, market cap, sector, etc.)
2. **Label generation:** Use the resolved win/loss labels from
   `signal_performance` as training targets (binary classification).
3. **Model selection:** Start with XGBoost or LightGBM (fast, interpretable).
   Scikit-learn logistic regression as a baseline.
4. **Training pipeline:** Nightly job that exports features + labels, retrains,
   and saves model artifact to `/storage/models/`.
5. **Inference:** Load model in `CredibilityScorer.score()` and replace heuristic
   adjustment with model prediction.
6. **Monitoring:** Track model accuracy over time, compare against heuristic
   baseline on the Confidence Calibration page.

**Dependencies:** scikit-learn or lightgbm (new pip dependency), sufficient
historical data (need ~500+ resolved signals for meaningful training).

**Risk:** Overfitting on small datasets, cold start with new event types.

**Files to touch:** `credibility/scorer.py`, new `credibility/ml_scorer.py`,
new training script, config for model path.

---

## Notes

- These items are tracked but not scheduled. Revisit after the current
  feature set is stable and deployed.
- Mobile responsive is the highest-priority backburner item since it affects
  user acquisition (social shares from mobile users).
