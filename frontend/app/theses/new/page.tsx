import { redirect } from "next/navigation";

import { CreateThesisForm } from "@/components/domain/CreateThesisForm";
import { getSignedInUser } from "@/lib/session";

export const dynamic = "force-dynamic";

export default async function NewThesisPage() {
  const user = await getSignedInUser();
  if (!user) {
    redirect("/login");
  }

  return (
    <main className="mx-auto flex w-full max-w-[700px] flex-1 flex-col gap-3 px-4 py-4">
      <CreateThesisForm />
    </main>
  );
}
