import {
  AFFILIATE_RECORD_ENDPOINTS,
  AFFILIATE_RECORD_PAGE_LIMIT,
  AFFILIATE_RECORD_PAGE_SIZE,
  AFFILIATE_RECORD_PER_PAGE_LIMIT,
  AFFILIATE_REFERRAL_STATUSES,
  AFFILIATE_COMMISSION_STATUSES,
  AffiliateRecordContractError,
  normaliseAffiliateRecordExpectedOwner,
  buildAffiliateRecordParams,
  normalizeAffiliateRecordResponse,
  createAffiliateRecordViewService,
  affiliateRecordError,
  isAffiliateRecordRequestCanceled,
  affiliateCommissionCsvCell,
  buildAffiliateCommissionsCsv,
  downloadAffiliateCommissionsPage,
} from './affiliateRecordViewService.js';

export {
  AFFILIATE_RECORD_ENDPOINTS,
  AFFILIATE_RECORD_PAGE_LIMIT,
  AFFILIATE_RECORD_PAGE_SIZE,
  AFFILIATE_RECORD_PER_PAGE_LIMIT,
  AFFILIATE_REFERRAL_STATUSES,
  AFFILIATE_COMMISSION_STATUSES,
  AffiliateRecordContractError,
  normaliseAffiliateRecordExpectedOwner,
  buildAffiliateRecordParams,
  normalizeAffiliateRecordResponse,
  createAffiliateRecordViewService,
  affiliateRecordError,
  isAffiliateRecordRequestCanceled,
  affiliateCommissionCsvCell,
  buildAffiliateCommissionsCsv,
  downloadAffiliateCommissionsPage,
};

/** Compatibility names consume complete HTTP payloads, not individual rows. */
const mapResponse = (kind, payload, options = {}) => {
  const params = buildAffiliateRecordParams(kind, {
    page: options.page ?? payload?.pagination?.page,
    perPage: options.perPage ?? payload?.pagination?.per_page,
    status: Object.prototype.hasOwnProperty.call(options, 'status')
      ? options.status : (payload?.filters?.status ?? null),
  });
  return normalizeAffiliateRecordResponse(kind, payload, {
    expectedOwner: options.expectedOwner,
    params,
  });
};

export const mapAffiliateReferrals = (payload, options = {}) => mapResponse('referrals', payload, options);
export const mapAffiliateCommissions = (payload, options = {}) => mapResponse('commissions', payload, options);
