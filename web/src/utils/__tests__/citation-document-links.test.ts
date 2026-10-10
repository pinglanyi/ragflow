import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import ts from 'typescript';

const files = [
  'components/markdown-content/index.tsx',
  'components/next-markdown-content/index.tsx',
  'components/floating-chat-widget-markdown.tsx',
  'pages/next-search/markdown-content/index.tsx',
];

function handler(file: string, locate: boolean) {
  // Run the real callback without importing the entire app/router in jsdom.
  const source = ts.createSourceFile(
    file,
    fs.readFileSync(path.resolve('src', file), 'utf8'),
    ts.ScriptTarget.Latest,
    true,
    ts.ScriptKind.TSX,
  );
  let callback: ts.Node | undefined;
  const visit = (node: ts.Node) => {
    if (
      ts.isVariableDeclaration(node) &&
      node.name.getText(source) === 'handleDocumentButtonClick' &&
      node.initializer &&
      ts.isCallExpression(node.initializer)
    ) {
      callback = node.initializer.arguments[0];
    }
    ts.forEachChild(node, visit);
  };
  visit(source);
  if (!callback) throw new Error(`Missing citation callback: ${file}`);
  const code = ts.transpileModule(
    `const factory = ${callback.getText(source)}; factory;`,
    { compilerOptions: { target: ts.ScriptTarget.ES2020 } },
  ).outputText;
  const open = jest.fn();
  const clickDocumentButton = jest.fn();
  const factory = vm.runInNewContext(code, {
    window: { open },
    clickDocumentButton,
    supportsSourceLocate: () => locate,
  });
  const click = (url?: string) =>
    factory(
      'doc-id',
      { id: 'chunk-id' },
      file.startsWith('pages/') ? locate : 'html',
      url,
    )();
  return { click, open, clickDocumentButton };
}

describe.each(files)('citation links in %s', (file) => {
  it('opens external web sources directly', () => {
    const subject = handler(file, false);
    subject.click('https://example.com/source');
    expect(subject.open).toHaveBeenCalledWith(
      'https://example.com/source',
      '_blank',
      'noopener,noreferrer',
    );
    expect(subject.clickDocumentButton).not.toHaveBeenCalled();
  });

  it('preserves the internal source locate drawer', () => {
    const subject = handler(file, true);
    subject.click();
    expect(subject.clickDocumentButton).toHaveBeenCalledWith('doc-id', {
      id: 'chunk-id',
    });
    expect(subject.open).not.toHaveBeenCalled();
  });
});
