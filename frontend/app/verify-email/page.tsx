import { redirect } from "next/navigation";

import { VerifyEmailForm } from "@/components/domain/VerifyEmailForm";
import { getSignedInUser } from "@/lib/session";

export default async function VerifyEmailPage() {
  const user = await getSignedInUser();
  if (!user) redirect("/login");
  if (user.email_verified) redirect("/");

  return (
    <main className="mx-auto flex w-full max-w-[1600px] flex-1 items-center px-4 py-12">
      <VerifyEmailForm email={user.email} />
    </main>
  );
}
