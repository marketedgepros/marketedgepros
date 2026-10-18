import assert from 'node:assert/strict';
import test from 'node:test';

const { default: api } = await import('../src/services/api.js');
const {
  AFFILIATE_PROGRAM_ENDPOINTS,
  AffiliateProgramContractError,
  loadAffiliateProgram,
  mapAffiliateProgram,
  mapAffiliateRegistration,
  registerAffiliate,
} = await import('../src/services/affiliateProgramViewService.js');

function adapterResponse(config, data, status = 200) {
  return {
    data,
    status,
    statusText: status === 201 ? 'Created' : 'OK',
    headers: {},
    config,
    request: {},
  };
}

test('affiliate program service uses central relative routes and preserves a valid zero commission rate', async () => {
  const originalAdapter = api.defaults.adapter;
  const requests = [];
  api.defaults.adapter = async (config) => {
    requests.push({ method: config.method, uri: api.getUri(config) });

    if (config.url === AFFILIATE_PROGRAM_ENDPOINTS.info) {
      return adapterResponse(config, {
        program: {
          is_active: true,
          commission_rate: 0,
          min_payout: 50,
          cookie_duration_days: 30,
          terms: 'Current terms',
        },
      });
    }

    if (config.url === AFFILIATE_PROGRAM_ENDPOINTS.register) {
      return adapterResponse(config, {
        message: 'Successfully registered as affiliate',
        link: { id: 7, code: 'TEST1234' },
      }, 201);
    }

    throw new Error(`Unexpected synthetic request: ${config.url}`);
  };

  try {
    const [program, registration] = await Promise.all([
      loadAffiliateProgram(),
      registerAffiliate(),
    ]);

    assert.deepEqual(requests, [
      { method: 'get', uri: '/api/v1/affiliate/info' },
      { method: 'post', uri: '/api/v1/affiliate/register' },
    ]);
    assert.deepEqual(program, {
      isActive: true,
      commissionRate: 0,
      minPayout: 50,
      cookieDurationDays: 30,
      terms: 'Current terms',
    });
    assert.deepEqual(registration, {
      message: 'Successfully registered as affiliate',
      link: { id: 7, code: 'TEST1234' },
    });
  } finally {
    api.defaults.adapter = originalAdapter;
  }
});

test('affiliate program contracts expose no rates for inactive data and reject malformed active or registration responses', () => {
  assert.deepEqual(mapAffiliateProgram({
    program: { is_active: false, commission_rate: 15, min_payout: 50, cookie_duration_days: 30 },
  }), {
    isActive: false,
    commissionRate: null,
    minPayout: null,
    cookieDurationDays: null,
    terms: null,
  });

  assert.throws(
    () => mapAffiliateProgram({
      program: { is_active: true, commission_rate: null, min_payout: 50, cookie_duration_days: 30 },
    }),
    AffiliateProgramContractError,
  );

  assert.throws(
    () => mapAffiliateRegistration({ message: 'Successfully registered as affiliate' }, 201),
    AffiliateProgramContractError,
  );

  assert.throws(
    () => mapAffiliateRegistration({
      message: 'Successfully registered as affiliate',
      link: { id: 7 },
    }, 202),
    AffiliateProgramContractError,
  );
});

test('affiliate plan rejects negative or out-of-range numbers instead of publishing invalid terms', () => {
  const base = { is_active: true, commission_rate: 15, min_payout: 50, cookie_duration_days: 30 };
  for (const patch of [
    { commission_rate: -1 }, { commission_rate: 101 },
    { min_payout: -50 }, { cookie_duration_days: -1 }, { cookie_duration_days: 1.5 },
  ]) {
    assert.throws(() => mapAffiliateProgram({ program: { ...base, ...patch } }), AffiliateProgramContractError);
  }
});
