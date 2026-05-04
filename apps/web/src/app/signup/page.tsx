import { redirect } from "next/navigation";

// Signup is now handled inside /login (tab toggle).
// Keep this route alive so old links and the landing page CTA still work.
export default function SignupPage() {
  redirect("/login");
}
