// install (please make sure versions match peerDependencies)
// yarn add @nivo/core @nivo/bar
// import { ResponsiveBar } from '@nivo/bar'
// import { data } from 'data.js'


if (!window.dash_clientside) {
    window.dash_clientside = {};
}

// make sure parent container have a defined height when using
// responsive component, otherwise height will be 0 and
// no chart will be rendered.
// website examples showcase many properties,
// you'll often use just a few of them.
window.dash_clientside.ui = {
    const: data = [
        {
            "country": "AD",
            "hot dog": 96,
            "hot dogColor": "hsl(176, 70%, 50%)",
            "burger": 187,
            "burgerColor": "hsl(227, 70%, 50%)",
            "sandwich": 81,
            "sandwichColor": "hsl(44, 70%, 50%)",
            "kebab": 24,
            "kebabColor": "hsl(191, 70%, 50%)",
            "fries": 42,
            "friesColor": "hsl(293, 70%, 50%)",
            "donut": 2,
            "donutColor": "hsl(318, 70%, 50%)"
        }
    ],
    // just to test callbacks
    testFunc: function (input) {
        return 'Test'
    },

    // recompute masonry layout
    recompute_masonry: function (is_open) {
        const $masonry = $('#cards');
        setTimeout(function () {
            $masonry.masonry()
        }, 155);
    },

    // generate a nivo bar chart to describe coins in the index
    // create_index_bar: function (input, plot_data = {data}) {
    //     return <ResponsiveBar
    //         data={plot_data}
    //         keys={['hot dog', 'burger', 'sandwich', 'kebab', 'fries', 'donut']}
    //         indexBy="country"
    //         margin={{top: 50, right: 130, bottom: 50, left: 60}}
    //         padding={0.3}
    //         layout="horizontal"
    //         valueScale={{type: 'linear'}}
    //         indexScale={{type: 'band', round: true}}
    //         valueFormat={{format: ' >-', enabled: false}}
    //         colors={{scheme: 'nivo'}}
    //         defs={[
    //             {
    //                 id: 'dots',
    //                 type: 'patternDots',
    //                 background: 'inherit',
    //                 color: '#38bcb2',
    //                 size: 4,
    //                 padding: 1,
    //                 stagger: true
    //             },
    //             {
    //                 id: 'lines',
    //                 type: 'patternLines',
    //                 background: 'inherit',
    //                 color: '#eed312',
    //                 rotation: -45,
    //                 lineWidth: 6,
    //                 spacing: 10
    //             }
    //         ]}
    //         fill={[
    //             {
    //                 match: {
    //                     id: 'fries'
    //                 },
    //                 id: 'dots'
    //             },
    //             {
    //                 match: {
    //                     id: 'sandwich'
    //                 },
    //                 id: 'lines'
    //             }
    //         ]}
    //         borderColor={{from: 'color', modifiers: [['darker', 1.6]]}}
    //         axisTop={null}
    //         axisRight={null}
    //         axisBottom={null}
    //         axisLeft={null}
    //         enableGridY={false}
    //         labelSkipWidth={12}
    //         labelSkipHeight={12}
    //         labelTextColor={{from: 'color', modifiers: [['darker', 1.6]]}}
    //         legends={[]}
    //     />
    // }

}
