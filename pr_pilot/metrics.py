try:
	from prometheus_client import Counter, Gauge
except Exception:
	# Define no-op fallbacks so importing metrics is safe when prometheus_client is not installed.
	class _NoopMetric:
		def __init__(self, *args, **kwargs):
			pass

		def labels(self, *args, **kwargs):
			return self

		def inc(self, amount=1):
			return None

		def set(self, value):
			return None

	Counter = _NoopMetric  # type: ignore
	Gauge = _NoopMetric  # type: ignore

# Total tokens consumed (estimate) by provider and repo
tokens_used = Counter('pr_pilot_tokens_used_total', 'Estimated tokens used by provider', ['provider', 'repo'])

# Total LLM call attempts and failures
llm_calls = Counter('pr_pilot_llm_calls_total', 'LLM calls made', ['provider', 'result'])

# Budget exhausted events
budget_exhausted = Counter('pr_pilot_budget_exhausted_total', 'Number of times budget was exhausted', ['repo'])

# Current remaining budget gauge (if available)
budget_remaining = Gauge('pr_pilot_budget_remaining', 'Remaining budget tokens for repo', ['repo'])
