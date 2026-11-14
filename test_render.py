"""Headless render test for app.py using streamlit's AppTest (no server, no browser)."""
import sys
from streamlit.testing.v1 import AppTest

at = AppTest.from_file("/root/hermes-ai-outreach/jobs/peakflo/prototype/app.py", default_timeout=120)
at.run()
assert not at.exception, f"initial render raised: {at.exception}"

print("initial_render=OK")
print("tabs=", [t.label for t in at.tabs])
print("selectboxes=", [s.label for s in at.selectbox])
print("buttons=", [b.label for b in at.button])

# pick each sample, run the agent, assert no exception and that a verdict appears
n = len(at.selectbox[0].options) if at.selectbox else 0
print("sample_options=", n)
routes = []
for i in range(n):
    at.selectbox[0].select_index(i).run()
    assert not at.exception, f"select {i} raised: {at.exception}"
    at.button[0].click().run()
    assert not at.exception, f"run {i} raised: {at.exception}"
    md = " ".join(m.value for m in at.markdown)
    for route in ("AUTO_POST", "HUMAN_REVIEW", "BLOCK", "auto_post", "human_review", "block"):
        if route in md:
            routes.append(route.lower())
            break
    else:
        routes.append("NO_VERDICT")

print("routes=", routes)
print("markdown_blocks=", len(at.markdown))
print("dataframes=", len(at.dataframe) if hasattr(at, "dataframe") else "n/a")
assert routes and "NO_VERDICT" not in routes, "a run produced no verdict badge"
print("APPTEST=ALL_GREEN")
