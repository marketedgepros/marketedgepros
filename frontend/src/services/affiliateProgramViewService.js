import api from './api.js';

export const AFFILIATE_PROGRAM_ENDPOINTS = Object.freeze({
  info: '/affiliate/info',
  register: '/affiliate/register',
});

export class AffiliateProgramContractError extends Error {
  constructor(message) {
    super(message);
    this.name = 'AffiliateProgramContractError';
  }
}

const isRecord = (value) => value !== null && typeof value === 'object' && !Array.isArray(value);

const requireRecord = (value, label) => {
  if (!isRecord(value)) {
    throw new AffiliateProgramContractError(`${label} had an unexpected response shape.`);
  }
  return value;
};

const requireFiniteNumber = (value, label) => {
  if (typeof value !== 'number' || !Number.isFinite(value) || value < 0) {
    throw new AffiliateProgramContractError(`${label} had an unexpected response shape.`);
  }
  return value;
};

const optionalText = (value) => (
  typeof value === 'string' && value.trim().length > 0 ? value : null
);

export const mapAffiliateProgram = (payload) => {
  const source = requireRecord(payload, 'Affiliate program');
  const program = requireRecord(source.program, 'Affiliate program details');

  if (typeof program.is_active !== 'boolean') {
    throw new AffiliateProgramContractError('Affiliate program active state had an unexpected response shape.');
  }

  if (!program.is_active) {
    return {
      isActive: false,
      commissionRate: null,
      minPayout: null,
      cookieDurationDays: null,
      terms: optionalText(program.terms),
    };
  }

  if (requireFiniteNumber(program.commission_rate, 'Affiliate commission rate') > 100
      || !Number.isSafeInteger(program.cookie_duration_days)) {
    throw new AffiliateProgramContractError('Affiliate program values are out of range.');
  }

  return {
    isActive: true,
    // Zero is a valid rate and must not be treated as an unavailable value.
    commissionRate: requireFiniteNumber(program.commission_rate, 'Affiliate commission rate'),
    minPayout: requireFiniteNumber(program.min_payout, 'Affiliate minimum payout'),
    cookieDurationDays: requireFiniteNumber(program.cookie_duration_days, 'Affiliate cookie duration'),
    terms: optionalText(program.terms),
  };
};

export const mapAffiliateRegistration = (payload, status) => {
  if (status !== 200 && status !== 201) {
    throw new AffiliateProgramContractError('Affiliate registration had an unexpected response status.');
  }

  const source = requireRecord(payload, 'Affiliate registration');
  const message = optionalText(source.message);
  if (!message) {
    throw new AffiliateProgramContractError('Affiliate registration had an unexpected response shape.');
  }

  return {
    message,
    link: requireRecord(source.link, 'Affiliate registration link'),
  };
};

export async function loadAffiliateProgram() {
  const response = await api.get(AFFILIATE_PROGRAM_ENDPOINTS.info);
  return mapAffiliateProgram(response.data);
}

export async function registerAffiliate() {
  const response = await api.post(AFFILIATE_PROGRAM_ENDPOINTS.register, {});
  return mapAffiliateRegistration(response.data, response.status);
}

export const isAffiliateProgramInactiveError = (error) => (
  error?.response?.status === 404
  && error?.response?.data?.error === 'Affiliate program is not active'
);

export const affiliateProgramError = (error) => (
  optionalText(error?.response?.data?.error)
  || optionalText(error?.response?.data?.message)
  || 'The affiliate program could not be loaded. Please try again.'
);
