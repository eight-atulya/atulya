export default {
    client: '@hey-api/client-fetch',
    input: '../../atulya-docs/static/openapi.json',
    output: {
        path: './generated',
        format: 'prettier',
    },
    plugins: [
        '@hey-api/typescript',
        '@hey-api/sdk',
    ],
};
