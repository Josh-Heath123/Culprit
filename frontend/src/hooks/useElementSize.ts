import { useEffect, useRef, useState } from "react";

/** Measures a container element's size. Deliberately not
 * @visx/responsive's ParentSize: that relies solely on ResizeObserver
 * firing, which some embedded/automated browser contexts defer or skip
 * entirely for non-composited frames — leaving a chart permanently
 * unsized. This combines a ResizeObserver (the normal, efficient path)
 * with an immediate synchronous measurement on mount, so the first
 * render always has a real size instead of waiting on a callback that
 * might not come. */
export function useElementSize<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [size, setSize] = useState({ width: 0, height: 0 });

  useEffect(() => {
    const element = ref.current;
    if (!element) return;

    const measure = () => {
      const rect = element.getBoundingClientRect();
      setSize({ width: rect.width, height: rect.height });
    };

    measure();

    const observer = new ResizeObserver(measure);
    observer.observe(element);
    window.addEventListener("resize", measure);

    return () => {
      observer.disconnect();
      window.removeEventListener("resize", measure);
    };
  }, []);

  return { ref, ...size };
}
