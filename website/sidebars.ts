import type {SidebarsConfig} from '@docusaurus/plugin-content-docs';

// This runs in Node.js - Don't use client-side code here (browser APIs, JSX...)

const sidebars: SidebarsConfig = {
  docsSidebar: [
    'index',
    {
      type: 'category',
      label: 'Guides',
      items: [
        'guides/installation',
        'guides/getting-started',
        'guides/cli-reference',
        'guides/configuration',
        'guides/output-modes',
      ],
    },
    {
      type: 'category',
      label: 'Recipes',
      items: [
        'recipes/scanning-local-files',
        'recipes/crawling-a-site',
        'recipes/excluding-links',
        'recipes/anchors-and-images',
        'recipes/baselines-and-incremental',
        'recipes/fixing-broken-links',
      ],
    },
    {
      type: 'category',
      label: 'Continuous Integration',
      items: ['ci/github-actions', 'ci/pre-commit', 'ci/issue-reporting'],
    },
    {
      type: 'category',
      label: 'AI agents',
      items: ['agents/index'],
    },
    'troubleshooting',
    'internals',
  ],
};

export default sidebars;
