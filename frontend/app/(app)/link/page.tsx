import type { Metadata } from "next";
import { Suspense } from "react";
import { Loading } from "@/components/ui";
import { LinkDetail } from "./link-detail";

export const metadata: Metadata = { title: "Link" };

export default function LinkPage() {
  return (
    <Suspense fallback={<Loading />}>
      <LinkDetail />
    </Suspense>
  );
}
