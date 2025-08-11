## HoloWellness Chatbot – Production Cost Estimate

Assumptions (editable)
- Region: ap-northeast-3 (Osaka)
- Runtime: 30 days/month
- Messages per user per day: 10
- Avg tokens per interaction (prompt + response): 800
- S3 storage used: 10 GB
- Egress to Internet: 30 GB/month (~1 GB/day)
- Peak concurrent users scenarios: 100 and 200 (used as a proxy for number of active users; see Notes)
- Models via OpenRouter:
  - gpt-oss-20b: $0.01 per 1K tokens (assumption)
  - gpt-oss-120b: $0.02 per 1K tokens (assumption)

Notes
- “AWS = free tier” means EC2 cost = $0 if you are still in the 12‑month free tier and your instance type qualifies. Otherwise use the “Upgrade” EC2 costs below.
- Concurrency mainly affects instance sizing; API cost is driven by total token volume. If your user counts differ from concurrency, replace N below accordingly.

Token math
- Tokens per user per month = 800 tokens/msg × 10 msgs/day × 30 days = 240,000 tokens
- For N users: monthly tokens = 240,000 × N
  - 100 users → 24,000,000 tokens
  - 200 users → 48,000,000 tokens

EC2 (on‑demand, Linux, estimates)
- t3.small ≈ $0.0264/hour → ~$19/month
- t3.medium ≈ $0.0528/hour → ~$38/month

Other AWS
- S3 Standard 10 GB → ~$0.23/month
- Data transfer out 30 GB (first 1 GB free, $0.09/GB thereafter) → ~$2.61/month

### Cost matrix

100 users
- AWS (free tier):
  - EC2: $0, S3: $0.23, Data: $2.61 → Infra subtotal: **$2.84**
  - API (gpt-oss-20b): 24,000,000/1,000 × $0.01 = **$240**
  - API (gpt-oss-120b): 24,000,000/1,000 × $0.02 = **$480**
  - Totals: 20b → **$242.84**/mo; 120b → **$482.84**/mo

- AWS (upgrade – t3.small):
  - EC2: ~$19, S3: $0.23, Data: $2.61 → Infra subtotal: **$21.84**
  - Totals: 20b → **$261.84**/mo; 120b → **$501.84**/mo

200 users
- AWS (free tier):
  - Infra subtotal still **$2.84**
  - API (gpt-oss-20b): 48,000,000/1,000 × $0.01 = **$480**
  - API (gpt-oss-120b): 48,000,000/1,000 × $0.02 = **$960**
  - Totals: 20b → **$482.84**/mo; 120b → **$962.84**/mo

- AWS (upgrade – t3.medium recommended for headroom):
  - EC2: ~$38, S3: $0.23, Data: $2.61 → Infra subtotal: **$40.84**
  - Totals: 20b → **$520.84**/mo; 120b → **$1,000.84**/mo

### How to adapt this sheet
- Replace “messages/day”, “tokens/interaction”, and users N to recompute: CostAPI = (N × msgs/day × tokens/interaction × 30 ÷ 1,000) × price_per_1K.
- Swap instance types as needed; monthly ≈ hourly_price × 720.
- If PDFs grow beyond 10 GB or traffic exceeds 30 GB/month, scale S3 and egress linearly.

### Caveats
- OpenRouter prices can change; confirm current rates for `gpt-oss-20b` and `gpt-oss-120b` in your account.
- Free‑tier eligibility varies by account, region, and instance family.

