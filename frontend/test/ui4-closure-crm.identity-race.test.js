import assert from "node:assert/strict";
import test from "node:test";
import { adminClosureCrmPrincipalFromAuth } from "../src/services/adminClosureCrmService.js";
import { createAdminClosureCrmIdentityBoundary } from "../src/hooks/useAdminClosureCrmIdentityGuard.js";

const principal = (id, tenantId, role = "master", name = "Admin") => (
  adminClosureCrmPrincipalFromAuth({ id, tenant_id: tenantId, role, first_name: name }, true)
);

const deferred = () => {
  let resolve;
  let reject;
  const promise = new Promise((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
};

test("CRM identity boundary keeps same-principal auth refresh stable but aborts all work on an auth/id/tenant/role switch", () => {
  const actorA = principal(9, 4, "master", "Before refresh");
  const boundary = createAdminClosureCrmIdentityBoundary(actorA);
  const stableLease = boundary.start();

  assert.equal(boundary.synchronize(principal(9, 4, "master", "After refresh")), false);
  assert.equal(stableLease.signal.aborted, false);
  assert.equal(stableLease.isCurrent(), true);

  for (const actorB of [
    principal(10, 4, "master"),
    principal(9, 5, "master"),
    principal(9, 4, "supermaster"),
    null,
  ]) {
    const prior = boundary.start();
    boundary.synchronize(actorB);
    assert.equal(prior.signal.aborted, true);
    assert.equal(prior.isCurrent(), false);
    boundary.synchronize(actorA);
  }
  boundary.cancelAll();
});

test("an old CRM mutation resolution cannot publish state, toast, navigation, or its follow-up refresh after an identity switch", async () => {
  const actorA = principal(9, 4);
  const actorB = principal(12, 7, "supermaster");
  const boundary = createAdminClosureCrmIdentityBoundary(actorA);
  const mutation = boundary.start();
  const response = deferred();
  const published = { state: [], toasts: [], navigations: [], refreshes: [] };

  const continuation = response.promise.then((result) => {
    if (!mutation.isCurrent()) return;
    published.state.push(result.lead);
    published.toasts.push("Lead saved");
    published.navigations.push("/admin/crm");
    const refresh = boundary.start();
    if (refresh.isCurrent()) published.refreshes.push(refresh.principal.owner.tenant_id);
    refresh.finish();
  });

  boundary.synchronize(actorB);
  assert.equal(mutation.signal.aborted, true);
  response.resolve({ lead: "tenant-A lead" });
  await continuation;

  assert.deepEqual(published, { state: [], toasts: [], navigations: [], refreshes: [] });
  const current = boundary.start();
  assert.equal(current.isCurrent(), true);
  assert.deepEqual(current.principal.owner, actorB.owner);
  current.finish();
});
