// SPDX-License-Identifier: MIT

export function License({
  item
}) {
  return <div data-testid="detail-tab-license">
      <p className="text-gray-900"><strong>{item.license}</strong></p>
      <pre className="whitespace-pre-wrap text-sm text-gray-500">
        {item.attribution || "No attribution text recorded."}
      </pre>
    </div>;
}
