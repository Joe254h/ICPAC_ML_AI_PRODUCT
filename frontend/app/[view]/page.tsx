import Platform from "@/features/platform";
import { notFound } from "next/navigation";
const views = ["forecasts","monitoring","verification","observations","models","products","bulletins","copilot","jobs","health","settings"];
export default async function Page({ params }: { params: Promise<{ view: string }> }) { const { view } = await params; if (!views.includes(view)) notFound(); return <Platform view={view} />; }
