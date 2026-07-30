import { cs } from '../i18n/cs';

export function Brand() {
  return (
    <div className="brand" aria-label={`${cs.brand}, ${cs.subtitle}`}>
      <strong>{cs.brand}</strong>
      <span>{cs.subtitle}</span>
    </div>
  );
}
