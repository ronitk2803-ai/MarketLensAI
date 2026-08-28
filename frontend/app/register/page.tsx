import { AuthForm } from "@/components/domain/AuthForm";
import { getAuthProviders } from "@/lib/api";

export default async function RegisterPage() {
  const providers = await getAuthProviders().catch(() => ({ google: false }));

  return <AuthForm mode="register" googleEnabled={providers.google} />;
}
