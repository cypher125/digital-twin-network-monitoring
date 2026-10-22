import type { Metadata } from "next";
import { Suspense } from "react";
import { Loading } from "@/components/ui";
import { ResultView } from "./result-view";

export const metadata: Metadata = { title: "Simulation result" };

export default function ResultPage() {
  return (
    <Suspense fallback={<Loading />}>
      <ResultView />
    </Suspense>
  );
}
