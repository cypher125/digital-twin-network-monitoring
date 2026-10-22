import type { Metadata } from "next";
import { Suspense } from "react";
import { Loading } from "@/components/ui";
import { DeviceDetail } from "./device-detail";

export const metadata: Metadata = { title: "Device" };

export default function DevicePage() {
  return (
    <Suspense fallback={<Loading />}>
      <DeviceDetail />
    </Suspense>
  );
}
