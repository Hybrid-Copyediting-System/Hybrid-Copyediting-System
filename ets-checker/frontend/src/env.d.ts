/// <reference types="vite/client" />

declare module "*.vue" {
  import type { DefineComponent } from "vue";
  const component: DefineComponent<object, object, unknown>;
  export default component;
}

declare module "vuetify/styles" {
  const styles: string;
  export default styles;
}

declare module "vuetify/components" {
  const components: Record<string, unknown>;
  export = components;
}

declare module "vuetify/directives" {
  const directives: Record<string, unknown>;
  export = directives;
}

declare module "vuetify/iconsets/mdi" {
  import type { IconSet } from "vuetify";
  export const aliases: Record<string, string>;
  export const mdi: IconSet;
}
