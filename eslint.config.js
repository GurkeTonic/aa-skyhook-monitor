export default [
    {
        languageOptions: {
            globals: {
                document: "readonly",
                window: "readonly",
                location: "readonly",
                setInterval: "readonly",
                setTimeout: "readonly",
                Date: "readonly",
                Math: "readonly",
                String: "readonly",
            },
        },
        rules: {
            "no-unused-vars": "warn",
            "no-undef": "error",
        },
    },
];
