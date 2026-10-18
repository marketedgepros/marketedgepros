import Documents from './user/Documents';

/**
 * /kyc remains a first-class protected entry point. It uses the same
 * one-file-per-type GET/POST/download document contract as the account and
 * trader document routes rather than submitting unsupported identity fields.
 */
export default function KYC() {
  return (
    <Documents
      mode="kyc"
      intro="Submit the requested documents for identity verification. Recorded document status is shown on this page."
    />
  );
}
