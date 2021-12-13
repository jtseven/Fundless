
// (function ($) {
//
// 	var $masonry = $('#cards');
// 	$masonry.masonry({
// 		itemSelector: '.card-item'
// 	}).on('shown.bs.collapse hidden.bs.collapse', function () {
// 		$masonry.masonry();
// 	});
//
// })(jQuery);

// var myCollapsible = document.getElementsByClassName('trades-collapse')
// myCollapsible.addEventListener('hidden.bs.collapse', function () {
//     const $masonry = $('#cards');
//     $masonry.masonry()
// })
//
// myCollapsible.addEventListener('shown.bs.collapse', function () {
//     const $masonry = $('#cards');
//     $masonry.masonry()
// })

if (!window.dash_clientside) {
    window.dash_clientside = {};
}

// create the "ui" namespace within dash_clientside
window.dash_clientside.ui = {
    // this function can be called by the python library
    jsFunction: function (is_open) {
        const $masonry = $('#cards');
		setTimeout(function(){
			$masonry.masonry()
		}, 300);

    }
}