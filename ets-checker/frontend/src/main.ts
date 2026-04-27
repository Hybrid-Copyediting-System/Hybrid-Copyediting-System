import { createApp } from "vue";
import { createVuetify } from "vuetify";
import * as components from "vuetify/components";
import * as directives from "vuetify/directives";
import { aliases, mdi } from "vuetify/iconsets/mdi";
import "vuetify/styles";
import "@mdi/font/css/materialdesignicons.css";
import App from "./App.vue";

const vuetify = createVuetify({
  components,
  directives,
  icons: {
    defaultSet: "mdi",
    aliases,
    sets: { mdi },
  },
  theme: {
    defaultTheme: "light",
    themes: {
      light: {
        colors: {
          primary: "#1976D2",
          secondary: "#424242",
          error: "#D32F2F",
          warning: "#F9A825",
          info: "#1976D2",
          success: "#388E3C",
        },
      },
      dark: {
        colors: {
          primary: "#42A5F5",
          secondary: "#616161",
          error: "#EF5350",
          warning: "#FFD54F",
          info: "#42A5F5",
          success: "#66BB6A",
        },
      },
    },
  },
});

createApp(App).use(vuetify).mount("#app");
