import { AuthForm } from "@/components/domain/AuthForm";
import { getAuthProviders } from "@/lib/api";

const ERRORS: Record<string, string> = {
  google: "Google sign-in didn't complete. Try again.",
  google_state:
    "That sign-in link expired or didn't match this browser. Start again from here.",
};

export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{ error?: string }>;
}) {
  const { error } = await searchParams;
  // A deployment without Google configured shouldn't show a button that can
  // only fail, and this must not depend on a build-time variable.
  const providers = await getAuthProviders().catch(() => ({ google: false }));

  return (
    <AuthForm
      mode="login"
      googleEnabled={providers.google}
      initialError={error ? ERRORS[error] : undefined}
    />
  );
}
