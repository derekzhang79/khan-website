var KnowledgeMap = {

    map: null,
    overlay: null,
    dictNodes: {},
    dictEdges: [],
    markers: [],
    widthPoints: 200,
    heightPoints: 120,
    selectedNodes: {},

    filteredNodes: {},
    updateFilterTimeout: null,

    nodeClickHandler: null,

    colors: {
        blue: "#0080C9",
        green: "#8EBE4F",
        red: "#E35D04",
        gray: "#FFFFFF"
    },
    icons: {
            Exercise: {
                    Proficient: "/images/node-complete.png?" + KA_VERSION,
                    Review: "/images/node-review.png?" + KA_VERSION,
                    Suggested: "/images/node-suggested.png?" + KA_VERSION,
                    Normal: "/images/node-not-started.png?" + KA_VERSION
                      },
            Summative: {
                    Normal: "/images/node-challenge-not-started.png?" + KA_VERSION,
                    Proficient: "/images/node-challenge-complete.png?" + KA_VERSION,
                    Suggested: "/images/node-challenge-suggested.png?" + KA_VERSION
                       }
    },
    latLngHome: new google.maps.LatLng(-0.064844, 0.736268),
    latMin: 90,
    latMax: -90,
    lngMin: 180,
    lngMax: -180,
    nodeSpacing: {lat: 0.392, lng: 0.35},
    latLngBounds: null,
    reZoom: /nodeLabelZoom(\d)+/g,
    reHidden: /nodeLabelHidden/g,
    reFiltered: /nodeLabelFiltered/g,
    fFirstDraw: true,
    fCenterChanged: false,
    fZoomChanged: false,
    graphDictModel: null,
    options: {
                getTileUrl: function(coord, zoom) {
                    // Sky tiles example from
                    // http://gmaps-samples-v3.googlecode.com/svn/trunk/planetary-maptypes/planetary-maptypes.html
                    return KnowledgeMap.getHorizontallyRepeatingTileUrl(coord, zoom, 
                            function(coord, zoom) {
                              return "/images/map-tiles/field_" +
                                 Math.floor(Math.random()*4+1) + '.jpg';
                            }
                )},
                tileSize: new google.maps.Size(256, 256),
                maxZoom: 10,
                minZoom: 7,
                isPng: false
    },

    init: function(latInit, lngInit, zoomInit, admin) {
        var self = this;

        this.graphDictModel = {
            'review': [],
            'suggested': [],
            'recent': [],
            'all': ko.observableArray([]),
            'userShowAll': ko.observable(false),
            'forceShowAll': ko.observable(false),
            'fastFilter': new KOFastFilter(),
        }

        // Initial setup of exercise list from embedded data

        $.each(graph_dict_data, function(idx, graphDict) {
            // TomY TODO ?App.version
            var s_prefix = graphDict.summative ? 'node-challenge' : 'node';

            if (graphDict.status == 'Suggested') {
                self.graphDictModel.suggested.push(graphDict);
                graphDict.badgeIcon = '/images/'+s_prefix+'-suggested.png';
            } else if (graphDict.status == 'Proficient') {
                graphDict.badgeIcon = '/images/'+s_prefix+'-complete.png';
            } else if (graphDict.status == 'Review') {
                self.graphDictModel.review.push(graphDict);
                graphDict.badgeIcon = '/images/node-review.png';
            } else {
                graphDict.badgeIcon = '/images/'+s_prefix+'-not-started.png';
            }
            
            if (graphDict.recent) {
                self.graphDictModel.recent.push(graphDict);
            }

            graphDict.inAllList = false;
            graphDict.visible = ko.observable(true);
            graphDict.clickHandler = function() {
                KnowledgeMap.nodeClickHandler(KnowledgeMap.dictNodes[graphDict.name], null);
            };
            graphDict.lowercase_name = graphDict.display_name.toLowerCase();
            graphDict.showBadge = ko.observable(false);

            KnowledgeMap.addNode({
                "id": graphDict.name,
                "name": graphDict.display_name,
                "h_position": graphDict.h_position,
                "v_position": graphDict.v_position,
                "status": graphDict.status,
                "summative": graphDict.summative
            });

            $.each(graphDict.prereqs, function(idx2, prereq) {
                KnowledgeMap.addEdge(graphDict.name, prereq, graphDict.summative);
            });
        });

        sum_function = function(list) {
            var count = 0;
            for (var idx = 0; idx < list.length; idx++) {
                if (list[idx].visible())
                    count++;
            }
            return count;
        };

        this.graphDictModel.suggested_count = KOBulkUpdate.dependentObservable(function() { return sum_function(this.review)+sum_function(this.suggested); }, this.graphDictModel);
        this.graphDictModel.recent_count = KOBulkUpdate.dependentObservable(function() { return sum_function(this.recent); }, this.graphDictModel);
        this.graphDictModel.all_count = KOBulkUpdate.dependentObservable(function() { return sum_function(this.all()); }, this.graphDictModel);
        this.graphDictModel.showAll = ko.dependentObservable(function() { return this.userShowAll() || this.forceShowAll(); }, this.graphDictModel);
        this.graphDictModel.all_total = graph_dict_data.length;

        this.graphDictModel.toggleShowAll = function() {
            if (KnowledgeMap.graphDictModel.userShowAll()) {
                KnowledgeMap.graphDictModel.userShowAll(false);
            } else {
                $.each(graph_dict_data, function(idx, graphDict) {
                    if (!graphDict.inAllList) {
                        KnowledgeMap.graphDictModel.all.push(graphDict);
                        graphDict.inAllList = true;
                    }
                });
                KnowledgeMap.graphDictModel.userShowAll(true);
            }
        };

        if (admin) {
            this.graphDictModel.toggleShowAll();
        }

        ko.applyBindings(this.graphDictModel, $('#exercise-list').get(0));

        this.admin = admin;
        this.map = new google.maps.Map(document.getElementById("map-canvas"), {
            mapTypeControl: false,
            streetViewControl: false,
            scrollwheel: false
        });

        var knowledgeMapType = new google.maps.ImageMapType(this.options);
        this.map.mapTypes.set('knowledge', knowledgeMapType);
        this.map.setMapTypeId('knowledge');

        if (latInit && lngInit && zoomInit)
        {
            this.map.setCenter(new google.maps.LatLng(latInit, lngInit));
            this.map.setZoom(zoomInit);
        }
        else
        {
            this.map.setCenter(this.latLngHome);
            this.map.setZoom(this.options.minZoom + 2);
        }

        this.layoutGraph();
        this.drawOverlay();

        this.latLngBounds = new google.maps.LatLngBounds(new google.maps.LatLng(this.latMin, this.lngMin), new google.maps.LatLng(this.latMax, this.lngMax)),

        google.maps.event.addListener(this.map, "center_changed", function(){KnowledgeMap.onCenterChange();});
        google.maps.event.addListener(this.map, "idle", function(){KnowledgeMap.onIdle();});
        google.maps.event.addListener(this.map, "click", function(){KnowledgeMap.onClick();});

        this.nodeClickHandler = function(node) {
            if (admin)
                window.location.href = '/editexercise?name='+node.id;
            else
                window.location.href = '/exercises?exid='+node.id;
        };

        this.giveNasaCredit();
        this.initFilter();
    },

    setNodeClickHandler: function(click_handler) {
        this.nodeClickHandler = click_handler;
    },

    panToNode: function(dataID) {
        var node = this.dictNodes[dataID];

        // Set appropriate zoom level if necessary
        if (node.summative && this.map.getZoom() > this.options.minZoom)
            this.map.setZoom(this.options.minZoom);
        else if (!node.summative && this.map.getZoom() == this.options.minZoom)
            this.map.setZoom(this.options.minZoom+1);

        // Move the node to the center of the view
        this.map.panTo(node.latLng);
    },

    escapeSelector: function(s) {
        return s.replace(/(:|\.)/g,'\\$1');
    },

    giveNasaCredit: function() {
        // Setup a copyright/credit line, emulating the standard Google style
        // From
        // http://code.google.com/apis/maps/documentation/javascript/demogallery.html?searchquery=Planetary
        var creditNode = $("<div class='creditLabel'>Image Credit: SDSS, DSS Consortium, NASA/ESA/STScI</div>");
        creditNode[0].index = 0;
        this.map.controls[google.maps.ControlPosition.BOTTOM_RIGHT].push(creditNode[0]);
    },

    layoutGraph: function() {

        var zoom = this.map.getZoom();

        for (var key in this.dictNodes)
        {
            this.drawMarker(this.dictNodes[key], zoom);
        }

        for (var key in this.dictEdges)
        {
            var rgTargets = this.dictEdges[key];
            for (var ix = 0; ix < rgTargets.length; ix++)
            {
                this.drawEdge(this.dictNodes[key], rgTargets[ix], zoom);
            }
        }
    },

    drawOverlay: function() {

        this.overlay = new com.redfin.FastMarkerOverlay(this.map, this.markers);
        this.overlay.drawOriginal = this.overlay.draw;
        this.overlay.draw = function() {
            this.drawOriginal();

            var jrgNodes = $(".nodeLabel");

            if (!KnowledgeMap.fFirstDraw)
            {
                KnowledgeMap.onZoomChange(jrgNodes);
            }

            jrgNodes.each(function(){
                KnowledgeMap.attachNodeEvents(this, KnowledgeMap.dictNodes[$(this).attr("data-id")]);
            });

            KnowledgeMap.fFirstDraw = false;
        }
    },

    attachNodeEvents: function(el, node) {
        $(el).click(
                function(evt){KnowledgeMap.onNodeClick(node, evt);}
            ).hover(
                function(){KnowledgeMap.onNodeMouseover(this, node);},
                function(){KnowledgeMap.onNodeMouseout(this, node);}
            );
    },

    addNode: function(node) {
        this.dictNodes[node.id] = node;
    },

    addEdge: function(source, target, summative) {
        if (!this.dictEdges[source]) this.dictEdges[source] = [];
        var rg = this.dictEdges[source];
        rg[rg.length] = {"target": target, "summative": summative};
    },

    nodeStatusCount: function(status) {
        var c = 0;
        for (var ix = 1; ix < arguments.length; ix++)
        {
            if (arguments[ix].status == status) c++;
        }
        return c;
    },

    drawEdge: function(nodeSource, edgeTarget, zoom) {

        var nodeTarget = this.dictNodes[edgeTarget.target];

        // If either of the nodes is missing, don't draw the edge.
        if (!nodeSource || !nodeTarget) return;

        var coordinates = [
            nodeSource.latLng,
            nodeTarget.latLng
        ];

        var countProficient = this.nodeStatusCount("Proficient", nodeSource, nodeTarget);
        var countSuggested = this.nodeStatusCount("Suggested", nodeSource, nodeTarget);
        var countReview = this.nodeStatusCount("Review", nodeSource, nodeTarget);

        var color = this.colors.gray;
        var weight = 1.0;
        var opacity = 0.48;

        if (countProficient == 2)
        {
            color = this.colors.blue;
            weight = 5.0;
            opacity = 1.0;
        }
        else if (countProficient == 1 && countSuggested == 1)
        {
            color = this.colors.green;
            weight = 5.0;
            opacity = 1.0;
        }
        else if (countReview > 0)
        {
            color = this.colors.red;
            weight = 5.0;
            opacity = 1.0;
        }

        edgeTarget.line = new google.maps.Polyline({
            path: coordinates,
            strokeColor: color,
            strokeOpacity: opacity,
            strokeWeight: weight,
            clickable: false,
            map: this.getMapForEdge(edgeTarget, zoom)
        });
    },

    drawMarker: function(node, zoom) {

        var lat = -1 * (node.h_position - 1) * this.nodeSpacing.lat;
        var lng = (node.v_position - 1) * this.nodeSpacing.lng;

        node.latLng = new google.maps.LatLng(lat, lng);

        if (lat < this.latMin) this.latMin = lat;
        if (lat > this.latMax) this.latMax = lat;
        if (lng < this.lngMin) this.lngMin = lng;
        if (lng > this.lngMax) this.lngMax = lng;

        var iconSet = this.icons[node.summative ? "Summative" : "Exercise"];
        var iconUrl = iconSet[node.status];
        if (!iconUrl) iconUrl = iconSet.Normal;

        var labelClass = "nodeLabel nodeLabel" + node.status;
        if (node.summative) labelClass += " nodeLabelSummative";

        node.iconUrl = iconUrl;

        var iconOptions = this.getIconOptions(node, zoom);
        var marker = new com.redfin.FastMarker(
                "marker-" + node.id, 
                node.latLng, 
                ["<div id='node-" + node.id + "' data-id='" + node.id + "' class='" + this.getLabelClass(labelClass, node, zoom, false) + "'><img src='" + iconOptions.url +"'/><div>" + node.name + "</div></div>"], 
                "", 
                node.summative ? 2 : 1,
                0,0);

        this.markers[this.markers.length] = marker;
    },

    getMapForEdge: function(edge, zoom) {
        return ((zoom == this.options.minZoom) == edge.summative) ? this.map : null;
    },

    getIconOptions: function(node, zoom) {

        var iconUrl = node.iconUrl;
        var iconUrlCacheKey = iconUrl + "@" + zoom;

        if (!this.iconCache) this.iconCache = {};
        if (!this.iconCache[iconUrlCacheKey])
        {
            var url = iconUrl;

            if (!node.summative && zoom <= this.options.minZoom)
            {
                url = iconUrl.replace(".png", "-star.png");
            }

            this.iconCache[iconUrlCacheKey] = {url: url};
        }
        return this.iconCache[iconUrlCacheKey];
    },

    getLabelClass: function(classOrig, node, zoom, filtered) {

        var visible = !node.summative || zoom == this.options.minZoom;
        classOrig = classOrig.replace(this.reHidden, "") + (visible ? "" : " nodeLabelHidden");

        if (node.summative && visible) zoom = this.options.maxZoom - 1;

        classOrig = classOrig.replace(this.reZoom, "") + (" nodeLabelZoom" + zoom);

        classOrig = classOrig.replace(this.reFiltered, "") + (filtered ? " nodeLabelFiltered" : "");

        return classOrig;
    },

    highlightNode: function(node, highlight) {
        var jel = $("#node-" + KnowledgeMap.escapeSelector(node.id));
        if (highlight)
            jel.addClass("nodeLabelHighlight");
        else
            jel.removeClass("nodeLabelHighlight");
    },

    onNodeClick: function(node, evt) {
        if (!node.summative && this.map.getZoom() <= this.options.minZoom)
            return;

        if (KnowledgeMap.admin)
        {
            if (evt.shiftKey)
            {
                if (node.id in KnowledgeMap.selectedNodes)
                {
                    delete KnowledgeMap.selectedNodes[node.id];
                    this.highlightNode(node, false);
                }
                else
                {
                    KnowledgeMap.selectedNodes[node.id] = true;
                    this.highlightNode(node, true);
                }
            }
            else
            {
                $.each(KnowledgeMap.selectedNodes, function(node_id) {
                    KnowledgeMap.highlightNode(KnowledgeMap.dictNodes[node_id], false);
                });
                KnowledgeMap.selectedNodes = { };
                KnowledgeMap.selectedNodes[node.id] = true;
                this.highlightNode(node, true);
            }
            
            //Unbind other keydowns to prevent a spawn of hell
            $(document).unbind('keydown');

            // If keydown is an arrow key
            $(document).keydown(function(e){
                var delta_v = 0, delta_h = 0;
                    
                if (e.keyCode == 37) { 
                    delta_v = -1; // Left
                }
                if (e.keyCode == 38) { 
                    delta_h = -1; // Up
                }
                if (e.keyCode == 39) { 
                    delta_v = 1; // Right
                }
                if (e.keyCode == 40) { 
                    delta_h = 1; // Down
                }

                if (delta_v != 0 || delta_h != 0) {
                    var id_array = [];

                    $.each(KnowledgeMap.selectedNodes, function(node_id) {
                        var actual_node = KnowledgeMap.dictNodes[node_id];

                        actual_node.v_position = parseInt(actual_node.v_position) + delta_v;
                        actual_node.h_position = parseInt(actual_node.h_position) + delta_h;

                        id_array.push(node_id);
                    });
                    $.post("/moveexercisemapnodes", { exercises: id_array.join(","), delta_h: delta_h, delta_v: delta_v } );

                    var zoom =KnowledgeMap.map.getZoom();
                    KnowledgeMap.markers = [];

                    for (var key in KnowledgeMap.dictEdges) // this loop lets us update the edges wand will remove the old edges
                    {
                        var rgTargets = KnowledgeMap.dictEdges[key];
                        for (var ix = 0; ix < rgTargets.length; ix++)
                        {
                            rgTargets[ix].line.setMap(null);
                        }
                    }
                    KnowledgeMap.overlay.setMap(null);
                    KnowledgeMap.layoutGraph();
                    KnowledgeMap.drawOverlay();

                    setTimeout(function() {
                            $.each(KnowledgeMap.selectedNodes, function(node_id) {
                                KnowledgeMap.highlightNode(KnowledgeMap.dictNodes[node_id], true);
                            });
                        }, 100);

                    return false;
                }
            });
            
            evt.stopPropagation();
        }
        else if (KnowledgeMap.nodeClickHandler)
        {
            KnowledgeMap.nodeClickHandler(node, evt);
        }
        else
        {
            // Go to exercise via true link click.
            $(".exercise-badge[data-id=\"" + KnowledgeMap.escapeSelector(node.id) + "\"] .exercise-title a").click();
        }
    },

    onNodeMouseover: function(el, node) {
        if (el.nodeName.toLowerCase() != "div")
            return;
        if (!node.summative && this.map.getZoom() <= this.options.minZoom)
            return;
        if (node.id in KnowledgeMap.selectedNodes)
            return;
      
        $(".exercise-badge[data-id=\"" + KnowledgeMap.escapeSelector(node.id) + "\"]").addClass("exercise-badge-hover");
        this.highlightNode(node, true);
        
    },

    onNodeMouseout: function(el, node) {
        if (el.nodeName.toLowerCase() != "div")
            return;
        if (!node.summative && this.map.getZoom() <= this.options.minZoom)
            return;
        if (node.id in KnowledgeMap.selectedNodes)
            return;
    
        $(".exercise-badge[data-id=\"" + KnowledgeMap.escapeSelector(node.id) + "\"]").removeClass("exercise-badge-hover");
        this.highlightNode(node, false);
    
    },

    onBadgeMouseover: function() {
        var exid = $(this).attr("data-id");
        if (exid in KnowledgeMap.selectedNodes)
            return;

        var node = KnowledgeMap.dictNodes[exid];
        if (node) KnowledgeMap.highlightNode(node, true);

        $(this).find('.exercise-show').show();
    },

    onBadgeMouseout: function() {
        var exid = $(this).attr("data-id");
        if (exid in KnowledgeMap.selectedNodes)
            return;

        var node = KnowledgeMap.dictNodes[exid];
        if (node) KnowledgeMap.highlightNode(node, false);

        $(this).find('.exercise-show').hide();
    },

    onShowExerciseClick: function(evt) {
        var exid = $(this).attr("data-id");
        KnowledgeMap.panToNode(exid);

        var node = KnowledgeMap.dictNodes[exid];
        if (node) KnowledgeMap.highlightNode(node, true);

        evt.stopPropagation();
    },

    onZoomChange: function(jrgNodes) {

        var zoom = this.map.getZoom();

        if (zoom < this.options.minZoom) return;
        if (zoom > this.options.maxZoom) return;

        this.fZoomChanged = true;

        jrgNodes.each(function() {
            var jel = $(this);
            var node = KnowledgeMap.dictNodes[jel.attr("data-id")];
            var filtered = !!KnowledgeMap.filteredNodes[jel.attr("data-id")];

            var iconOptions = KnowledgeMap.getIconOptions(node, zoom);
            $("img", jel).attr("src", iconOptions.url);
            jel.attr("class", KnowledgeMap.getLabelClass(jel.attr("class"), node, zoom, filtered));
        });

        for (var key in this.dictEdges)
        {
            var rgTargets = this.dictEdges[key];
            for (var ix = 0; ix < rgTargets.length; ix++)
            {
                var line = rgTargets[ix].line;
                var map = this.getMapForEdge(rgTargets[ix], zoom);
                if (line.getMap() != map) line.setMap(map);
            }
        }
    },

    onIdle: function() {

        if (!this.fCenterChanged && !this.fZoomChanged)
            return;

        // Panning by 0 pixels forces a redraw of our map's markers
        // in case they aren't being rendered at the correct size.
        KnowledgeMap.map.panBy(0, 0);

        var center = this.map.getCenter();
        $.post("/savemapcoords", {
            "lat": center.lat(),
            "lng": center.lng(),
            "zoom": this.map.getZoom()
        }); // Fire and forget
    },

    onClick: function() {
        if (KnowledgeMap.admin) {
            $.each(KnowledgeMap.selectedNodes, function(node_id) {
                KnowledgeMap.highlightNode(KnowledgeMap.dictNodes[node_id], false);
            });
            KnowledgeMap.selectedNodes = { };
        }
    },

    onCenterChange: function() {

        this.fCenterChanged = true;

        var center = this.map.getCenter();
        if (this.latLngBounds.contains(center)) {
            return;
        }

        var C = center;
        var X = C.lng();
        var Y = C.lat();

        var AmaxX = this.latLngBounds.getNorthEast().lng();
        var AmaxY = this.latLngBounds.getNorthEast().lat();
        var AminX = this.latLngBounds.getSouthWest().lng();
        var AminY = this.latLngBounds.getSouthWest().lat();

        if (X < AminX) {X = AminX;}
        if (X > AmaxX) {X = AmaxX;}
        if (Y < AminY) {Y = AminY;}
        if (Y > AmaxY) {Y = AmaxY;}

        this.map.setCenter(new google.maps.LatLng(Y,X));
    },

    getHorizontallyRepeatingTileUrl: function(coord, zoom, urlfunc) {

        // From http://gmaps-samples-v3.googlecode.com/svn/trunk/planetary-maptypes/planetary-maptypes.html
        var y = coord.y;
        var x = coord.x;

        // tile range in one direction range is dependent on zoom level
        // 0 = 1 tile, 1 = 2 tiles, 2 = 4 tiles, 3 = 8 tiles, etc
        var tileRange = 1 << zoom;

        // don't repeat across y-axis (vertically)
        if (y < 0 || y >= tileRange) {
            return null;
        }

        // repeat across x-axis
        if (x < 0 || x >= tileRange) {
            x = (x % tileRange + tileRange) % tileRange;
        }

        return urlfunc({x:x,y:y}, zoom);
    },

    // Filtering

    initFilter: function() {
        $('#dashboard-filter-text').keyup(function() {
            if (KnowledgeMap.updateFilterTimeout == null) {
                KnowledgeMap.updateFilterTimeout = setTimeout(function() {
                    KnowledgeMap.doFilter();
                    KnowledgeMap.updateFilterTimeout = null;
                }, 250);
            }
        });
        
        $('#dashboard-filter-clear').click(function() {
            KnowledgeMap.clearFilter();
        });
        $('#dashboard-filter-text').val('');
    },

    clearFilter: function() {
        $('#dashboard-filter-text').val('');
        this.doFilter();
    },

    doFilter: function() {
        var filterText = $.trim($('#dashboard-filter-text').val().toLowerCase());

        this.graphDictModel.forceShowAll(filterText != '');

        KOBulkUpdate.pause();
        $.each(graph_dict_data, function(idx, graphDict) {
            var visible = (graphDict.lowercase_name.indexOf(filterText) >= 0);
            if (KnowledgeMap.graphDictModel.showAll() && visible && !graphDict.inAllList) {
                KnowledgeMap.graphDictModel.all.push(graphDict);
                graphDict.inAllList = true;
            }
            graphDict.visible(visible);
            KnowledgeMap.filteredNodes[graphDict.name] = !visible;
        });
        KOBulkUpdate.resume();

        this.graphDictModel.fastFilter.doFilter('#exercise-list', function(data) { return (data.lowercase_name.indexOf(filterText) >= 0); });

        if (filterText) {
            $('#dashboard-filter-clear').show();
        } else {
            $('#dashboard-filter-clear').hide();
        }

        var jrgNodes = $(".nodeLabel");
        KnowledgeMap.onZoomChange(jrgNodes);
    }
};
