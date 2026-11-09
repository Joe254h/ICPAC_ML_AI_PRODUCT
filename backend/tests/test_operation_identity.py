"""A lost submission response must not enqueue another scientific operation."""

from concurrent.futures import ThreadPoolExecutor

from backend.tests.test_forecasts import env as env


def test_concurrent_and_completed_resubmissions_reuse_one_operation(env):
    capability = env.client.get("/operations/capabilities")
    assert capability.status_code == 200
    assert capability.json() == {"idempotent_submission": True}
    body = {"action": "past_weeks", "actor": "Joe254h", "request_id": "a" * 32}
    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(lambda _: env.client.post("/operations", json=body), range(4)))
    assert all(response.status_code == 202 for response in responses)
    ids = {response.json()["id"] for response in responses}
    assert ids == {"request-" + "a" * 32}
    records = env.platform.repo.list("operation")
    assert len(records) == 1
    record = records[0]
    record.update(status="complete", result={"verified": []})
    env.platform.repo.save("operation", record, record["id"])
    recovered = env.client.post("/operations", json=body)
    assert recovered.status_code == 202
    assert recovered.json()["status"] == "complete"
    assert len(env.platform.repo.list("operation")) == 1
    different = env.client.post("/operations", json={**body, "action": "cycle"})
    assert different.status_code == 422
    assert len(env.platform.repo.list("operation")) == 1
