import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

/** Buttons, on the design tokens (index.css). `default` is the one filled
 * violet action on a screen; `secondary`, `outline` and `ghost` are
 * quieter. Never lime: lime is the culprit, not an action (I2). Focus is
 * the global :focus-visible violet ring, which no variant removes. A press
 * settles the button by a pixel (I6); reduced motion turns it off. */
const buttonVariants = cva(
  "inline-flex shrink-0 items-center justify-center gap-1.5 whitespace-nowrap rounded-md text-sm font-medium transition duration-150 ease-out select-none active:translate-y-px disabled:pointer-events-none disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
  {
    variants: {
      variant: {
        default: "bg-brand-fill text-on-brand-fill shadow-raised hover:bg-brand-fill-hover",
        outline: "border border-line-strong bg-transparent text-fg hover:border-fg-subtle hover:bg-surface-2",
        secondary: "bg-surface-2 text-fg hover:bg-surface-3",
        ghost: "text-fg-muted hover:bg-surface-2 hover:text-fg",
        destructive: "border border-fail-line bg-fail-tint text-fail hover:bg-surface-3",
        link: "text-brand underline-offset-4 hover:underline",
      },
      size: {
        default: "h-9 px-3.5",
        sm: "h-8 px-2.5 text-xs",
        lg: "h-10 px-4",
        icon: "size-9",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  },
);

function Button({
  className,
  variant,
  size,
  asChild = false,
  ...props
}: React.ComponentProps<"button"> &
  VariantProps<typeof buttonVariants> & { asChild?: boolean }) {
  const Comp = asChild ? Slot : "button";
  return (
    <Comp
      data-slot="button"
      className={cn(buttonVariants({ variant, size, className }))}
      {...props}
    />
  );
}

export { Button, buttonVariants };
