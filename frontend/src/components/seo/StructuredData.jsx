import { Helmet } from 'react-helmet-async';
import { buildPublicSchema, publicSiteOrigin, serializePublicSchema } from '../../services/publicMetadataService';

export default function StructuredData({ type = 'website', data = {} }) {
  const origin = publicSiteOrigin(import.meta.env.VITE_PUBLIC_SITE_URL);
  const schema = buildPublicSchema(type, data, origin);
  if (!schema) return null;
  return (
    <Helmet>
      <script type="application/ld+json">{serializePublicSchema(schema)}</script>
    </Helmet>
  );
}
