import type { Metadata } from "next";
import { Suspense } from "react";
import { Loading } from "@/components/ui";
import { TrendsView } from "./trends-view";

export const metadata: Metadata = { title: "Trends" };

export default function TrendsPage() {
  return (
    <Suspense fallback={<Loading />}>
      <TrendsView />
    </Suspense>
  );
}
