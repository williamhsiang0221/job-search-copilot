import type { ReactNode } from "react";
import { usePrivacy } from "../privacy";

// Fixed-width regardless of the real value, so hiding it doesn't also leak
// its length.
const PLACEHOLDER = "••••••";

export default function MaskedText({ children }: { children: ReactNode }) {
  const { masked } = usePrivacy();
  return <>{masked ? PLACEHOLDER : children}</>;
}
