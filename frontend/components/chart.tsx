"use client";
import { useEffect, useRef } from "react";
import * as echarts from "echarts";
export default function Chart({ option, height = 230 }: { option: echarts.EChartsOption; height?: number }) { const container = useRef<HTMLDivElement>(null); useEffect(() => { if (!container.current) return; const chart = echarts.init(container.current); chart.setOption(option); const observer = new ResizeObserver(() => chart.resize()); observer.observe(container.current); return () => { observer.disconnect(); chart.dispose(); }; }, [option]); return <div ref={container} style={{ height, width: "100%" }} role="img" aria-label="Computed synthetic climate comparison chart" />; }
