// Build script for the MoQ player bundle.
//
// Some MoQ watch packages use Vite-specific "?worker&url" query imports for
// audio web workers. We stub those out (return an empty URL string) because
// the demo sources are video-only, so the audio worklet never actually fires.
import * as esbuild from 'esbuild';
import { mkdirSync, readFileSync } from 'fs';

mkdirSync('static', { recursive: true });

const workerUrlPlugin = {
  name: 'vite-worker-url',
  setup(build) {
    // Resolve "path/to/file?worker&url" → namespace:worker-stub
    build.onResolve({ filter: /\?worker/ }, () => ({
      path: 'worker-stub',
      namespace: 'worker-stub',
    }));
    // Return an empty URL string so the audio worklet silently no-ops
    build.onLoad({ filter: /.*/, namespace: 'worker-stub' }, () => ({
      contents: 'export default ""',
      loader: 'js',
    }));
  },
};

// Keep a compatibility patch for older catalog schema layouts that still
// require `priority` in the video and audio objects.
function patchPriority(contents) {
  // Each catalog file has TWO `priority: z.number()...` lines: one in the
  // backward-compat TrackSchema and one in the main object schema.
  // replaceAll ensures both are made optional so missing == 128.
  return contents.replaceAll(
    'priority: z.number().int().min(0).max(255),',
    'priority: z.number().int().min(0).max(255).optional().default(128),'
  );
}

const schemaPatchPlugin = {
  name: 'catalog-schema-patch',
  setup(build) {
    build.onLoad({ filter: /catalog\/video\.js$/ }, (args) => ({
      contents: patchPriority(readFileSync(args.path, 'utf8')),
      loader: 'js',
    }));
    build.onLoad({ filter: /catalog\/audio\.js$/ }, (args) => ({
      contents: patchPriority(readFileSync(args.path, 'utf8')),
      loader: 'js',
    }));
  },
};

const result = await esbuild.build({
  entryPoints: ['moq-player.js'],
  bundle:      true,
  format:      'esm',
  outfile:     'static/hang.js',
  logLevel:    'info',
  plugins:     [workerUrlPlugin, schemaPatchPlugin],
  target:      ['chrome115'],   // WebTransport + WebCodecs baseline
});

if (result.errors.length === 0) {
  const { statSync } = await import('node:fs');
  const bytes = statSync('static/hang.js').size;
  console.log(`hang.js bundled (${(bytes / 1024).toFixed(0)} KB)`);
}
