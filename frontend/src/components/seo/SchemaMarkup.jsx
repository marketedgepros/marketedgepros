import { Helmet } from 'react-helmet-async';
import { buildPublicSchema, publicSiteOrigin, serializePublicSchema } from '../../services/publicMetadataService';

export default function SchemaMarkup() {
  const origin = publicSiteOrigin(import.meta.env.VITE_PUBLIC_SITE_URL);
  const schema = buildPublicSchema('organization', {}, origin);
  return (
    <Helmet>
      <script type="application/ld+json">{serializePublicSchema(schema)}</script>
    </Helmet>
  );
}
