import { defineConfig } from 'astro/config';
import tailwind from '@astrojs/tailwind';

export default defineConfig({
  site: 'https://pranavraut033.github.io/telegram-backup',
  integrations: [tailwind()],
});
