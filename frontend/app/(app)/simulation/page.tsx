import type { Metadata } from "next";
import { Suspense } from "react";
import { Loading } from "@/components/ui";
import { SimulationConsole } from "./simulation-console";

export const metadata: Metadata = { title: "Simulation" };

export default function SimulationPage() {
  return (
    <Suspense fallback={<Loading />}>
      <SimulationConsole />
    </Suspense>
  );
}
