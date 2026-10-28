"use client";
import { useEffect, useRef } from "react";
import * as echarts from "echarts";
import { forNight, useTheme } from "@/lib/theme";
export default function Chart({
  option,
  height = 230,
  label = "Chart",
}: {
  option: echarts.EChartsOption;
  height?: number;
  label?: string;
}) {
  const container = useRef<HTMLDivElement>(null);
  const [theme] = useTheme();
  useEffect(() => {
    if (!container.current) return;
    const chart = echarts.init(container.current);
    chart.setOption(theme === "dark" ? forNight(option) : option);
    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(container.current);
    return () => {
      observer.disconnect();
      chart.dispose();
    };
  }, [option, theme]);
  return (
    <div
      ref={container}
      style={{ height, width: "100%" }}
      role="img"
      aria-label={label}
    />
  );
}
