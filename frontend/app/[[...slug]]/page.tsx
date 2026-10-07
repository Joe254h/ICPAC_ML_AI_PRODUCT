import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { resolveRoute } from "@/features/routes";
import View from "@/features/view";

type Props = {
  params: Promise<{ slug?: string[] }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
};

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const route = resolveRoute((await params).slug);
  return { title: route && route.path ? route.title : undefined };
}

export default async function Page({ params, searchParams }: Props) {
  const route = resolveRoute((await params).slug);
  if (!route) notFound();
  const query = await searchParams;
  const id = typeof query.id === "string" ? query.id : undefined;
  return <View path={route.path} id={id} />;
}
